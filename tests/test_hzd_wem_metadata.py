"""HZD wem-metadata stage (issue #31): must reuse the catalog stage's harvested
core-path list (via a sidecar) instead of repeating the full-pack content scan, and
must not silently swallow per-core / per-line parse failures -- exactly the stage
family that once silently lost ~1,109 story lines (sentence_fw.py's `ff 0f` marker
history)."""
import csv


from deciwaves.games.hzd import wem_metadata
from deciwaves.engine.catalog_io import (
    write_core_paths_sidecar, read_core_paths_sidecar, read_core_paths_sidecar_header,
)
from deciwaves.games.hzd.profile import cores_sidecar_header
from deciwaves.games.hzd.sentence_fw import LineMedia


class _FakeReader:
    """Stand-in for HzdPackage.read_core: returns fixed per-path bytes, or raises for
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


def _real_package_dir(tmp_path, name="pkg"):
    """A real directory shaped like a valid HZDR package dir (has
    PackFileLocators.bin), needed wherever locators_fingerprint/cores_sidecar_header
    must compute for real -- build_profile itself stays mocked via _patch_profile."""
    pkg = tmp_path / name
    pkg.mkdir(exist_ok=True)
    locators = pkg / "PackFileLocators.bin"
    if not locators.is_file():
        locators.write_bytes(b"x")
    return str(pkg)


def _argv(tmp_path, cores, catalog=None, out=None, errors=None, extra=()):
    catalog = catalog or (tmp_path / "catalog.csv")
    out = out or (tmp_path / "wem-metadata.csv")
    errors = errors or (tmp_path / "wem-metadata-errors.log")
    return [
        # A real, valid package dir so the issue-#53 preflight passes; build_profile
        # itself stays mocked via _patch_profile, so no real pack is read.
        "--package", _real_package_dir(tmp_path),
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
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

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
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

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
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

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
# (a2) staleness detection (issue #45): the sidecar's locators-fingerprint header
# tells wem-metadata whether catalog-cores.txt still matches the live pack.
# ---------------------------------------------------------------------------

def test_matching_locators_header_trusts_sidecar_silently(tmp_path, monkeypatch, capsys):
    pkg = _real_package_dir(tmp_path)
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/mq/scene/sentences"],
                             header=cores_sidecar_header(pkg))

    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    argv = _argv(tmp_path, cores_sidecar, catalog=catalog, out=out)
    argv[argv.index("--package") + 1] = pkg
    rc = wem_metadata.main(argv)

    assert rc == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["line_id"] for r in rows] == ["L1"]
    printed = capsys.readouterr().out
    assert "STALE" not in printed.upper()
    assert "WARNING" not in printed


def test_mismatched_locators_header_warns_ignores_and_regenerates(tmp_path, monkeypatch, capsys):
    pkg = _real_package_dir(tmp_path)
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/stale/scene/sentences"],
                             header="# locators: 999:999")  # deliberately wrong fingerprint

    harvested = ["localized/sentences/fresh/scene/sentences"]
    reader = _FakeReader({"localized/sentences/fresh/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    monkeypatch.setattr(wem_metadata, "harvest_sentence_cores", lambda fw, sample_cap=None: harvested)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    argv = _argv(tmp_path, cores_sidecar, catalog=catalog, out=out)
    argv[argv.index("--package") + 1] = pkg
    rc = wem_metadata.main(argv)

    assert rc == 0
    printed = capsys.readouterr().out
    assert "STALE" in printed.upper()
    assert str(cores_sidecar) in printed
    # the stale sidecar's list was ignored -- only the fresh re-harvest's core was read
    assert reader.read_calls == ["localized/sentences/fresh/scene/sentences"]
    # the sidecar is overwritten with a fresh header + fresh path list
    assert read_core_paths_sidecar_header(str(cores_sidecar)) == cores_sidecar_header(pkg)
    assert read_core_paths_sidecar(str(cores_sidecar)) == harvested


def test_mismatched_header_with_sample_cap_does_not_overwrite_sidecar(tmp_path, monkeypatch, capsys):
    """A capped re-harvest is truncated -- overwriting the shared sidecar with it would
    poison it the same way an uncapped `hzd catalog` run already guards against
    (c50547e). The stale sidecar is left exactly as-is; only this run's own output uses
    the (possibly truncated) fresh list."""
    pkg = _real_package_dir(tmp_path)
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/stale/scene/sentences"],
                             header="# locators: 999:999")
    before = cores_sidecar.read_bytes()

    harvested = ["localized/sentences/fresh/scene/sentences"]
    reader = _FakeReader({"localized/sentences/fresh/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    monkeypatch.setattr(wem_metadata, "harvest_sentence_cores", lambda fw, sample_cap=None: harvested)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    argv = _argv(tmp_path, cores_sidecar, catalog=catalog, out=out, extra=["--sample-cap", "1"])
    argv[argv.index("--package") + 1] = pkg
    rc = wem_metadata.main(argv)

    assert rc == 0
    assert cores_sidecar.read_bytes() == before   # untouched, not poisoned by a capped re-harvest
    assert "sample-cap" in capsys.readouterr().out.lower()


def test_legacy_sidecar_with_no_header_is_trusted_with_one_warning(tmp_path, monkeypatch, capsys):
    """Back-compat (issue #45): a sidecar written before this feature existed has no
    header at all -- staleness can't be checked, so it's trusted as-is (no forced
    regeneration on every pre-existing workspace), but a warning is printed once."""
    pkg = _real_package_dir(tmp_path)
    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/mq/scene/sentences"])  # no header

    reader = _FakeReader({"localized/sentences/mq/scene/sentences": b"CORE_BYTES"})
    _patch_profile(monkeypatch, reader)
    _forbid_rescan(monkeypatch)
    monkeypatch.setattr(
        wem_metadata, "parse_sentence_media",
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

    catalog = tmp_path / "catalog.csv"
    _write_minimal_catalog(catalog, ["L1"])
    out = tmp_path / "wem-metadata.csv"

    argv = _argv(tmp_path, cores_sidecar, catalog=catalog, out=out)
    argv[argv.index("--package") + 1] = pkg
    rc = wem_metadata.main(argv)

    assert rc == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["line_id"] for r in rows] == ["L1"]   # still trusted/used, not re-harvested
    printed = capsys.readouterr().out
    assert printed.count("can't be checked") == 1


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
        lambda core_bytes, on_line_error=None, core_path=None: [LineMedia("L1", 0, 100, 530)])

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

    def _fake_parse(core_bytes, on_line_error=None, core_path=None):
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


# ---------------------------------------------------------------------------
# (c) main(): a bad --package (issue #53) must fail actionably, like every other
# HZD stage got in #49/#34 -- not with a raw FileNotFoundError traceback from
# HzdLocators. This stage is documented standalone-usable, so the gap was
# user-visible. The check must run before build_profile touches the pack, so this
# needs no sidecar/catalog files to exist.
# ---------------------------------------------------------------------------

def test_wem_metadata_main_missing_package_fails_actionably(tmp_path, capsys):
    bad_package = tmp_path / "install_root"  # exists, but no PackFileLocators.bin
    bad_package.mkdir()

    rc = wem_metadata.main(["--package", str(bad_package),
                            "--out", str(tmp_path / "wem-metadata.csv")])

    assert rc == 1
    captured = capsys.readouterr()
    assert "--hzd-package" in captured.out
    assert "PackFileLocators.bin" in captured.out
    assert captured.err == ""  # no traceback
