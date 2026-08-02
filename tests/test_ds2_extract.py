"""DS2 fast-path batch extractor: resumable, fail-soft manifest + WAV decode.

Install-free (mirrors the stub harness in tests/test_fw_extract.py): the whole
package/decoder chain is stubbed, so the resume/sidecar/error bookkeeping runs
on any machine with no DS2 install and no vgmstream-cli.
"""
import csv
import os
from collections import namedtuple

import pytest

from deciwaves.engine.tool_paths import resolve
from deciwaves.games.ds2 import extract as fx

VGMSTREAM = resolve("DECIWAVES_VGMSTREAM", "vgmstream-cli")


def test_extract_fails_fast_on_missing_vgmstream(tmp_path):
    """decode=True with a missing vgmstream must raise BEFORE the run, writing nothing.

    Guards against the resume-poisoning trap: a bad vgmstream path would make every
    line log+mark-processed, so a re-run after fixing the path extracted nothing."""
    out = tmp_path / "ds2"
    with pytest.raises(fx.DecodeError):
        fx.extract(str(tmp_path / "no_pkg"), str(out),
                   decode=True, vgmstream=str(tmp_path / "missing-vgmstream-cli.exe"))
    # nothing was created: no processed log, no manifest, no audio dir
    assert not (out / "clip-index-processed.txt").exists()
    assert not (out / "clip-index.csv").exists()


# --- stub harness: fake graph/store/line-iterator/decoder, no install ----------
_FakeLoc = namedtuple("_FakeLoc", "file_index offset")
_FakeLine = namedtuple("_FakeLine", "line_id group_id lssr_index locator")


class _FakeGraph:
    # Enough entries for _FakeLoc.file_index to index into (usually 15).
    # Include the cache:package/ prefix so _derive_region strips it for real.
    files = ["cache:package/l200_aus/package.39.00.core.stream"] * 20


def _fake_lines(n):
    return [_FakeLine(f"g1_{i:04d}", 1, i, _FakeLoc(15, i * 100)) for i in range(n)]


def _install_ds2_stubs(monkeypatch, lines, *, fail_line_ids=frozenset(),
                       non_riff_offsets=frozenset(), jitter=0.0):
    """Stub the whole DS2 package/decoder chain so extract() runs with no install:
    a fake streaming graph, a fake stream store, a fake line iterator (two-arg
    ``iter_ds2_lines(graph, package_dir)``), and a fake decoder that writes a wav
    (or raises for `fail_line_ids`). `non_riff_offsets` makes the store's
    ``read_riff_clip`` raise ``ValueError``, exactly like a real non-RIFF locator."""
    import time

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _FakeGraph()))

    class _FakeStore:
        def __init__(self, *a, **k):
            pass

        def read_riff_clip(self, file_index, offset):
            if offset in non_riff_offsets:
                raise ValueError(f"no RIFF at file {file_index} offset {offset}")
            if jitter:
                time.sleep((offset // 100 % 5) * jitter)  # completion order != input order
            return b"\x00" * 32

    monkeypatch.setattr(fx, "FwStreamStore", _FakeStore)
    monkeypatch.setattr(fx, "iter_ds2_lines", lambda graph, package_dir: iter(lines))

    def fake_decode(clip_bytes, wav_path, vgmstream=None):
        lid = os.path.splitext(os.path.basename(wav_path))[0]
        if lid in fail_line_ids:
            raise fx.DecodeError(f"boom {lid}")
        with open(wav_path, "wb") as f:
            f.write(b"WAVEDATA")

    monkeypatch.setattr(fx, "decode_clip", fake_decode)


def _read_rows(out):
    with open(os.path.join(out, "clip-index.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_extract_clean_run_writes_manifest(tmp_path, monkeypatch):
    """A clean run writes a valid manifest with one row per line (duplicate clip
    offsets preserved as separate rows, keyed on line_id) plus the processed sidecar."""
    lines = _fake_lines(5)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    _install_ds2_stubs(monkeypatch, lines)

    stats = fx.extract("pkg", str(tmp_path / "ds2"), decode=True, vgmstream=str(vg), jobs=1)

    assert (stats.ok, stats.failed, stats.skipped) == (5, 0, 0)
    rows = _read_rows(str(tmp_path / "ds2"))
    assert len(rows) == 5
    assert rows[0]["line_id"] == "g1_0000"
    assert all(int(r["clip_bytes"]) > 0 for r in rows)
    # duplicate clip offsets (reused lines) must NOT be de-duplicated: all 5 rows
    # share offset 0..400 distinct here; the manifest is keyed on line_id alone.
    assert len({r["line_id"] for r in rows}) == 5
    processed = fx.processed_core_paths(os.path.join(str(tmp_path / "ds2"),
                                                     "clip-index-processed.txt"))
    assert processed == {ln.line_id for ln in lines}


def test_extract_resume_skips_processed_lines(tmp_path, monkeypatch):
    """A resumed run skips already-processed lines -- no duplicate manifest rows."""
    lines = _fake_lines(6)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "ds2")

    _install_ds2_stubs(monkeypatch, lines)
    s1 = fx.extract("pkg", out, limit=4, decode=True, vgmstream=str(vg), jobs=1)
    assert s1.ok == 4

    _install_ds2_stubs(monkeypatch, lines)  # fresh line iterator
    s2 = fx.extract("pkg", out, limit=4, decode=True, vgmstream=str(vg), jobs=1)
    assert s2.skipped == 4
    assert s2.ok == 2

    ids = [r["line_id"] for r in _read_rows(out)]
    assert len(ids) == len(set(ids)) == 6   # 4 + 2, no dupes


def test_extract_per_line_decode_failure_is_logged_and_does_not_abort(tmp_path, monkeypatch):
    """A per-line decode failure is logged to extract-errors.log, does not abort the
    run, and is left OFF the processed sidecar so it's retried on the next resume."""
    lines = _fake_lines(4)
    bad = {"g1_0001", "g1_0003"}
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "ds2")
    _install_ds2_stubs(monkeypatch, lines, fail_line_ids=bad, jitter=0.001)

    stats = fx.extract("pkg", out, decode=True, vgmstream=str(vg), jobs=4)

    assert (stats.ok, stats.failed) == (2, 2)
    rows = _read_rows(out)
    assert len(rows) == 2
    assert {r["line_id"] for r in rows} == {ln.line_id for ln in lines} - bad

    err_lines = [ln for ln in
                 open(os.path.join(out, "extract-errors.log"), encoding="utf-8")
                 .read().splitlines() if ln]
    assert len(err_lines) == 2
    assert {ln.split("\t")[0] for ln in err_lines} == bad
    for ln in err_lines:
        assert len(ln.split("\t")) == 2   # line_id \t message -- not corrupted/interleaved

    processed = fx.processed_core_paths(os.path.join(out, "clip-index-processed.txt"))
    assert processed == {ln.line_id for ln in lines} - bad  # failed lines retried next resume


def test_extract_non_riff_read_is_counted_as_failed(tmp_path, monkeypatch):
    """A clip whose bytes don't start with RIFF (FwStreamStore.read_riff_clip raises
    ValueError -- the 7 known non-RIFF locators) is counted as a per-line failure,
    logged, does not abort the run, and is not recorded as done."""
    lines = _fake_lines(3)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "ds2")
    _install_ds2_stubs(monkeypatch, lines, non_riff_offsets={100})  # g1_0001's offset

    stats = fx.extract("pkg", out, decode=True, vgmstream=str(vg), jobs=2)

    assert (stats.ok, stats.failed) == (2, 1)
    rows = _read_rows(out)
    assert {r["line_id"] for r in rows} == {"g1_0000", "g1_0002"}
    err_lines = [ln for ln in
                 open(os.path.join(out, "extract-errors.log"), encoding="utf-8")
                 .read().splitlines() if ln]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("g1_0001\tValueError:")
    processed = fx.processed_core_paths(os.path.join(out, "clip-index-processed.txt"))
    assert processed == {"g1_0000", "g1_0002"}  # the non-RIFF line stays outstanding


def test_extract_retries_a_failed_line_on_resume(tmp_path, monkeypatch):
    """A per-line failure (here: a non-RIFF read) is not permanently marked done --
    it stays eligible and succeeds on the next resume, ending up in the manifest
    exactly once."""
    lines = _fake_lines(3)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "ds2")

    _install_ds2_stubs(monkeypatch, lines, non_riff_offsets={100})
    s1 = fx.extract("pkg", out, decode=True, vgmstream=str(vg), jobs=1)
    assert (s1.ok, s1.failed) == (2, 1)

    _install_ds2_stubs(monkeypatch, lines)  # non-RIFF condition cleared
    s2 = fx.extract("pkg", out, decode=True, vgmstream=str(vg), jobs=1)
    assert (s2.ok, s2.failed) == (1, 0)
    assert s2.skipped == 2

    rows = _read_rows(out)
    ids = [r["line_id"] for r in rows]
    assert len(ids) == len(set(ids)) == 3
    assert ids.count("g1_0001") == 1


def test_main_prints_errors_log_path_when_there_are_failures(tmp_path, monkeypatch, capsys):
    lines = _fake_lines(3)
    _install_ds2_stubs(monkeypatch, lines, fail_line_ids={"g1_0001"})
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", str(vg))
    out = str(tmp_path / "ds2")

    rc = fx.main(["--package", "pkg", "--out-dir", out])
    assert rc == 0
    captured = capsys.readouterr()
    assert "failed=1" in captured.out
    assert os.path.join(out, "extract-errors.log") in captured.out


def test_decode_clip_resolves_vgmstream_at_spawn_time_not_import_time(tmp_path, monkeypatch):
    """Regression mirror of FW's issue #25 test: setting DECIWAVES_VGMSTREAM after
    import (this test file's top-of-file `from deciwaves.games.ds2 import extract`)
    must still be picked up at spawn time, not frozen at def/import time."""
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", r"C:\fake\vgmstream-cli.exe")
    seen = []

    class _FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        seen.append(args[0])
        # decode_clip writes atomically (tmp -> os.replace); the stub must produce
        # the output the real vgmstream would, or the move has nothing to move.
        # vgmstream's invocation is `-o <out> <input>` -- the wav is the -o target.
        with open(args[args.index("-o") + 1], "wb") as f:
            f.write(b"\x00" * 64)
        return _FakeProc()

    monkeypatch.setattr(fx.subprocess, "run", fake_run)
    fx.decode_clip(b"\x00" * 8, str(tmp_path / "out.wav"))
    assert seen == [r"C:\fake\vgmstream-cli.exe"], (
        "decode_clip's default vgmstream path must re-resolve DECIWAVES_VGMSTREAM at "
        "call time, not freeze it at import/def time")


# ---------------------------------------------------------------------------
# region column (issue #388)
# ---------------------------------------------------------------------------

def test_extract_writes_region_column_from_graph_files(tmp_path, monkeypatch):
    lines = _fake_lines(3)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    _install_ds2_stubs(monkeypatch, lines)

    stats = fx.extract("pkg", str(tmp_path / "ds2"), decode=True, vgmstream=str(vg), jobs=1)
    assert stats.ok == 3
    rows = _read_rows(str(tmp_path / "ds2"))
    assert all("region" in r for r in rows)
    assert rows[0]["region"] == "l200_aus"


def test_derive_region_root_when_no_directory():
    assert fx._derive_region("cache:package/package.01.00.core.stream") == "root"


def test_derive_region_extracts_first_path_component():
    assert fx._derive_region("cache:package/l700_bea/something.core.stream") == "l700_bea"


def test_derive_region_strips_cache_prefix_first():
    assert fx._derive_region("cache:package/l100_mex/deep/path.stream") == "l100_mex"


# ---------------------------------------------------------------------------
# backfill (issue #388 amendment)
# ---------------------------------------------------------------------------

def _write_manifest_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _make_backfill_graph():
    """Stub graph with two file entries at known indices: index 0 has a
    regional directory, index 1 is root-level (no directory)."""
    class G:
        files = ["cache:package/l200_aus/package.39.00.core.stream",
                 "cache:package/package.01.00.core.stream"]
    return G


def test_backfill_adds_region_column_to_existing_manifest(tmp_path, monkeypatch):
    out_dir = str(tmp_path / "ds2")
    os.makedirs(out_dir)
    manifest_path = os.path.join(out_dir, "clip-index.csv")
    old_cols = ["line_id", "group_id", "lssr_index", "file_index",
                "offset", "clip_bytes", "wav"]
    _write_manifest_csv(manifest_path, [
        {"line_id": "g1_0000", "group_id": "1", "lssr_index": "0",
         "file_index": "0", "offset": "100", "clip_bytes": "32",
         "wav": "audio/g1_0000.wav"},
        {"line_id": "g2_0000", "group_id": "2", "lssr_index": "0",
         "file_index": "1", "offset": "200", "clip_bytes": "48",
         "wav": "audio/g2_0000.wav"},
    ], old_cols)

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _make_backfill_graph()))

    n = fx.backfill_region("pkg", out_dir)
    assert n == 2

    from deciwaves.engine.catalog_io import read_csv_rows
    rows = read_csv_rows(manifest_path)
    assert len(rows) == 2
    assert all("region" in r for r in rows)
    assert rows[0]["region"] == "l200_aus"
    assert rows[1]["region"] == "root"
    assert "line_id" in rows[0]  # old columns preserved


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    out_dir = str(tmp_path / "ds2")
    os.makedirs(out_dir)
    manifest_path = os.path.join(out_dir, "clip-index.csv")
    new_cols = fx.MANIFEST_COLS
    _write_manifest_csv(manifest_path, [
        {"line_id": "g1_0000", "group_id": "1", "lssr_index": "0",
         "file_index": "0", "offset": "100", "clip_bytes": "32",
         "wav": "audio/g1_0000.wav", "region": "l200_aus"},
    ], new_cols)

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _make_backfill_graph()))

    n = fx.backfill_region("pkg", out_dir)
    assert n == 0  # no-op

    from deciwaves.engine.catalog_io import read_csv_rows
    rows = read_csv_rows(manifest_path)
    assert len(rows) == 1
    assert rows[0]["region"] == "l200_aus"  # unchanged


def test_backfill_no_csv_nothing_to_do(tmp_path, monkeypatch, capsys):
    out_dir = str(tmp_path / "ds2")
    os.makedirs(out_dir)

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _make_backfill_graph()))

    n = fx.backfill_region("pkg", out_dir)
    assert n == 0
    assert "nothing to do" in capsys.readouterr().out


def test_backfill_empty_csv_nothing_to_do(tmp_path, monkeypatch):
    out_dir = str(tmp_path / "ds2")
    os.makedirs(out_dir)
    manifest_path = os.path.join(out_dir, "clip-index.csv")
    old_cols = ["line_id", "group_id", "lssr_index", "file_index",
                "offset", "clip_bytes", "wav"]
    _write_manifest_csv(manifest_path, [], old_cols)

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _make_backfill_graph()))

    n = fx.backfill_region("pkg", out_dir)
    assert n == 0


# ---------------------------------------------------------------------------
# stale-header guard (issue #388 amendment)
# ---------------------------------------------------------------------------

def test_extract_refuses_stale_header_without_region(tmp_path, monkeypatch, capsys):
    out_dir = str(tmp_path / "ds2")
    os.makedirs(out_dir)
    manifest_path = os.path.join(out_dir, "clip-index.csv")
    old_cols = ["line_id", "group_id", "lssr_index", "file_index",
                "offset", "clip_bytes", "wav"]
    _write_manifest_csv(manifest_path, [
        {"line_id": "g1_0000", "group_id": "1", "lssr_index": "0",
         "file_index": "0", "offset": "100", "clip_bytes": "32",
         "wav": "audio/g1_0000.wav"},
    ], old_cols)
    # Also need a processed sidecar so prune_incomplete_rows doesn't
    # "reconstruct" — we just want a stale-header detection.
    with open(os.path.join(out_dir, "clip-index-processed.txt"), "w") as pf:
        pf.write("g1_0000\n")

    lines = _fake_lines(2)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    _install_ds2_stubs(monkeypatch, lines)

    stats = fx.extract("pkg", out_dir, decode=True, vgmstream=str(vg), jobs=1)
    assert stats.ok == 0
    captured = capsys.readouterr()
    assert "region" in captured.out
    assert "--backfill" in captured.out
