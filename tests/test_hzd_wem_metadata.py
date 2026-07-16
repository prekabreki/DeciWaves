"""HZD wem-metadata stage (issue #31): must reuse the catalog stage's harvested
core-path list (via a sidecar) instead of repeating the full-pack content scan, and
must not silently swallow per-core / per-line parse failures -- exactly the stage
family that once silently lost ~1,109 story lines (sentence_fw.py's `ff 0f` marker
history)."""
import csv

import pytest

from deciwaves.games.hzd import wem_metadata
from deciwaves.engine.catalog_io import write_core_paths_sidecar
from deciwaves.games.hzd.sentence_fw import LineMedia


class _FakeReader:
    """Stand-in for FwPackage.read_core: returns fixed per-path bytes, or raises for
    paths listed in fail_paths (simulating a corrupt/unreadable core)."""

    def __init__(self, cores: dict, fail_paths=()):
        self.cores = cores
        self.fail_paths = set(fail_paths)
        self.read_calls = []

    def read_core(self, path):
        self.read_calls.append(path)
        if path in self.fail_paths:
            raise ValueError(f"boom reading {path}")
        return self.cores[path]


class _FakeProfile:
    def __init__(self, reader):
        self.pack_reader = reader


def _patch_profile(monkeypatch, reader):
    monkeypatch.setattr(wem_metadata, "build_profile", lambda package: _FakeProfile(reader))


def _forbid_rescan(monkeypatch):
    """Fail loudly if harvest_sentence_cores is called -- proves the sidecar path was
    used instead of repeating catalog's full-pack scan."""
    def _boom(*a, **k):
        raise AssertionError("harvest_sentence_cores must not run when the sidecar is present")
    monkeypatch.setattr(wem_metadata, "harvest_sentence_cores", _boom)


def _write_minimal_catalog(path, line_ids):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["line_id", "category", "subtitle_en"])
        for lid in line_ids:
            w.writerow([lid, "main_quest", "Hello"])


def _argv(tmp_path, cores, catalog=None, out=None, errors=None, extra=()):
    catalog = catalog or (tmp_path / "catalog.csv")
    out = out or (tmp_path / "wem-metadata.csv")
    errors = errors or (tmp_path / "wem-metadata-errors.log")
    return [
        "--package", "FAKE_PKG",
        "--out", str(out),
        "--catalog", str(catalog),
        "--cores", str(cores),
        "--errors", str(errors),
        *extra,
    ]


# ---------------------------------------------------------------------------
# (a) sidecar consumption: no rescan when the catalog-produced list is present
# ---------------------------------------------------------------------------

def test_uses_cores_sidecar_and_never_rescans(tmp_path, monkeypatch):
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/mq/scene/sentences"])

    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    rc = wem_metadata.main(_argv(tmp_path, cores_sidecar, catalog=catalog, out=out))

    assert rc == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["line_id"] for r in rows] == ["L1"]
    assert reader.read_calls == ["localized/sentences/mq/scene/sentences"]


def test_main_accepts_bare_filename_out(tmp_path, monkeypatch):
    """A bare filename (no directory component) --out must not crash: os.makedirs on
    an empty dirname raises FileNotFoundError unless the path is abspath'd first."""
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/mq/scene/sentences"])

    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    monkeypatch.chdir(tmp_path)

    rc = wem_metadata.main(_argv(tmp_path, cores_sidecar, catalog=catalog, out="wem-metadata.csv"))

    assert rc == 0
    assert (tmp_path / "wem-metadata.csv").is_file()


def test_falls_back_to_rescan_and_still_excludes_simpletext_when_sidecar_missing(
        tmp_path, monkeypatch, capsys):
    """Standalone usability: if wem-metadata is run without a prior `hzd catalog` (no
    sidecar on disk), it must still work by rescanning -- and the rescan fallback must
    apply the same dialogue-only filter catalog.select_sentence_cores applies, so
    /simpletext cores (which can't contain sentences) are never handed to the parser."""
    harvested = [
        "localized/sentences/mq/scene/sentences",
        "localized/sentences/voices/aloy/simpletext",
    ]
    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)

    calls = {"n": 0}

    def _fake_harvest(fw, sample_cap=None):
        calls["n"] += 1
        return harvested
    monkeypatch.setattr(wem_metadata, "harvest_sentence_cores", _fake_harvest)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None: [LineMedia("L1", 0, 100, 530)])

    missing_sidecar = tmp_path / "no-such-cores.txt"
    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    rc = wem_metadata.main(_argv(tmp_path, missing_sidecar, catalog=catalog, out=out))

    assert rc == 0
    assert calls["n"] == 1
    # only the /sentences path was ever read -- /simpletext was filtered out, same as
    # catalog.select_sentence_cores would do.
    assert reader.read_calls == ["localized/sentences/mq/scene/sentences"]
    printed = capsys.readouterr().out.lower()
    assert "rescan" in printed


# ---------------------------------------------------------------------------
# (b) error observability: failures land in an errors file, not the void
# ---------------------------------------------------------------------------

def test_records_core_read_error_and_continues_with_other_cores(tmp_path, monkeypatch):
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), [
        "localized/sentences/bad/scene/sentences",
        "localized/sentences/good/scene/sentences",
    ])
    reader = _FakeReader(
        {"localized/sentences/good/scene/sentences": b"CORE_BYTES"},
        fail_paths=["localized/sentences/bad/scene/sentences"],
    )
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"
    errors_path = tmp_path / "wem-metadata-errors.log"

    rc = wem_metadata.main(_argv(tmp_path, cores_sidecar, catalog=catalog, out=out, errors=errors_path))

    assert rc == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["line_id"] for r in rows] == ["L1"]  # the good core still produced output
    err_text = errors_path.read_text(encoding="utf-8")
    assert "localized/sentences/bad/scene/sentences" in err_text
    assert "ValueError" in err_text


def test_records_line_level_parse_error(tmp_path, monkeypatch):
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/mq/scene/sentences"])
    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)

    def _fake_parse(core_bytes, on_line_error=None):
        if on_line_error:
            on_line_error("L_broken", "no sound body for sentence uuid")
        return []
    monkeypatch.setattr(wem_metadata, "parse_sentence_media", _fake_parse)

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L_broken"])
    out = tmp_path / "wem-metadata.csv"
    errors_path = tmp_path / "wem-metadata-errors.log"

    rc = wem_metadata.main(_argv(tmp_path, cores_sidecar, catalog=catalog, out=out, errors=errors_path))

    assert rc == 0
    err_text = errors_path.read_text(encoding="utf-8")
    assert "L_broken" in err_text
    assert "no sound body for sentence uuid" in err_text
