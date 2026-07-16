"""FW fast-path batch extractor: resumable, fail-soft manifest + WAV decode.

The resume unit test needs no install. The extraction tests skip without the FW
install (and the decode test also without VGAudio).
"""
import csv
import os
import wave

import pytest

from deciwaves.engine.tool_paths import resolve
from deciwaves.games.fw import extract as fx

VGAUDIO = resolve("DECIWAVES_VGAUDIO", "VGAudioCli")


def test_load_done_unions_manifest_and_processed(tmp_path):
    manifest = tmp_path / "clip-index.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fx.MANIFEST_COLS)
        w.writeheader()
        w.writerow({"line_id": "g1_0000", "group_id": 1, "lssr_index": 0,
                    "file_index": 15, "offset": 0, "clip_bytes": 10, "wav": "audio/x.wav"})
    processed = tmp_path / "processed.txt"
    processed.write_text("g2_0000\ng3_0001\n", encoding="utf-8")

    done = fx.load_done(str(manifest), str(processed))
    assert done == {"g1_0000", "g2_0000", "g3_0001"}


def test_load_done_missing_files(tmp_path):
    assert fx.load_done(str(tmp_path / "nope.csv"), str(tmp_path / "nope.txt")) == set()


def test_extract_fails_fast_on_missing_vgaudio(tmp_path):
    """decode=True with a missing VGAudio must raise BEFORE the run, writing nothing.

    Guards against the resume-poisoning trap: previously a bad VGAudio path made every
    line log+mark-processed, so a re-run after fixing the path extracted nothing."""
    out = tmp_path / "fw"
    with pytest.raises(fx.DecodeError):
        fx.extract(str(tmp_path / "no_pkg"), str(out),
                   decode=True, vgaudio=str(tmp_path / "missing-vgaudio.exe"))
    # nothing was created: no processed log, no manifest, no audio dir
    assert not (out / "clip-index-processed.txt").exists()
    assert not (out / "clip-index.csv").exists()


def test_extract_manifest_and_resume(fw_package_dir, tmp_path):
    """--no-decode: resolve a few lines, write a valid manifest, and skip them
    on a second run (resume)."""
    out = str(tmp_path / "fw")
    s1 = fx.extract(str(fw_package_dir), out, limit=5, decode=False)
    assert s1.ok == 5 and s1.failed == 0

    manifest = os.path.join(out, "clip-index.csv")
    with open(manifest, newline="", encoding="utf-8") as f:
        rows1 = list(csv.DictReader(f))
    assert len(rows1) == 5
    assert all(int(r["file_index"]) in {15, 16, 101} for r in rows1)  # an English stream
    assert all(int(r["clip_bytes"]) > 0 for r in rows1)
    first_ids = {r["line_id"] for r in rows1}
    assert len(first_ids) == 5                                 # unique ids

    # second run (limit counts NEW work): the first 5 are skipped, the next 5
    # extracted -- resume guarantee is "never re-extract a done line".
    s2 = fx.extract(str(fw_package_dir), out, limit=5, decode=False)
    assert s2.skipped >= 5
    with open(manifest, newline="", encoding="utf-8") as f:
        rows2 = list(csv.DictReader(f))
    ids2 = [r["line_id"] for r in rows2]
    assert len(ids2) == len(set(ids2))                         # no duplicate rows
    assert first_ids.issubset(set(ids2))                       # originals retained, not re-done


@pytest.mark.skipif(not os.path.isfile(VGAUDIO), reason="VGAudio not present")
def test_extract_decodes_real_wav(fw_package_dir, tmp_path):
    out = str(tmp_path / "fw")
    s = fx.extract(str(fw_package_dir), out, limit=3, decode=True)
    assert s.ok == 3 and s.failed == 0
    with open(os.path.join(out, "clip-index.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        wav_path = os.path.join(out, r["wav"])
        assert os.path.isfile(wav_path)
        with wave.open(wav_path, "rb") as w:
            assert w.getframerate() == 48000
            assert w.getnframes() > 0


# --- parallel extraction (issue #41): stubbed graph/store/decoder, no install ---
from collections import namedtuple

_FakeLoc = namedtuple("_FakeLoc", "file_index offset")
_FakeLine = namedtuple("_FakeLine", "line_id group_id lssr_index locator")


class _FakeGraph:
    files = ["en/package.01.00.core.stream"]


def _fake_lines(n):
    return [_FakeLine(f"g1_{i:04d}", 1, i, _FakeLoc(15, i * 100)) for i in range(n)]


def _install_fw_stubs(monkeypatch, lines, *, fail_line_ids=frozenset(), jitter=0.0):
    """Stub the whole FW package/decoder chain so extract() runs with no install:
    a fake streaming graph, a fake stream store, a fake line iterator, and a fake
    decoder that writes a wav (or raises for `fail_line_ids`)."""
    import time

    monkeypatch.setattr(fx.StreamingGraph, "from_file",
                        staticmethod(lambda path: _FakeGraph()))

    class _FakeStore:
        def __init__(self, *a, **k):
            pass

        def read_riff_clip(self, file_index, offset):
            if jitter:
                time.sleep((offset // 100 % 5) * jitter)  # completion order != input order
            return b"\x00" * 32

    monkeypatch.setattr(fx, "FwStreamStore", _FakeStore)
    monkeypatch.setattr(fx, "iter_english_lines", lambda graph: iter(lines))

    def fake_decode(clip_bytes, wav_path, vgaudio=None):
        lid = os.path.splitext(os.path.basename(wav_path))[0]
        if lid in fail_line_ids:
            raise fx.DecodeError(f"boom {lid}")
        with open(wav_path, "wb") as f:
            f.write(b"WAVEDATA")

    monkeypatch.setattr(fx, "decode_clip", fake_decode)


def _read_rows(out):
    with open(os.path.join(out, "clip-index.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_extract_parallel_matches_serial(tmp_path, monkeypatch):
    """Manifest rows (content AND order), ok/failed counts must be identical for
    --jobs 1 and --jobs 8."""
    lines = _fake_lines(40)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")

    def run(jobs, tag):
        _install_fw_stubs(monkeypatch, lines, jitter=0.001)
        out = str(tmp_path / tag)
        stats = fx.extract("pkg", out, decode=True, vgaudio=str(vg), jobs=jobs)
        return stats, _read_rows(out)

    (s_stats, s_rows) = run(1, "serial")
    (p_stats, p_rows) = run(8, "parallel")

    assert (p_stats.ok, p_stats.failed) == (s_stats.ok, s_stats.failed) == (40, 0)
    assert [r["line_id"] for r in p_rows] == [r["line_id"] for r in s_rows]
    assert p_rows == s_rows, "parallel manifest must match serial row-for-row"


def test_extract_parallel_failure_is_fail_soft_and_errors_line_atomic(tmp_path, monkeypatch):
    """A per-line decode failure under the pool is logged and the run continues;
    the errors file has exactly one clean, uninterleaved line per failure."""
    lines = _fake_lines(30)
    bad = {"g1_0005", "g1_0011", "g1_0023"}
    _install_fw_stubs(monkeypatch, lines, fail_line_ids=bad, jitter=0.001)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "fw")

    stats = fx.extract("pkg", out, decode=True, vgaudio=str(vg), jobs=8)

    assert (stats.ok, stats.failed) == (27, 3)
    rows = _read_rows(out)
    assert len(rows) == 27
    assert {r["line_id"] for r in rows} == {ln.line_id for ln in lines} - bad

    err_lines = [ln for ln in
                 open(os.path.join(out, "extract-errors.log"), encoding="utf-8")
                 .read().splitlines() if ln]
    assert len(err_lines) == 3
    assert {ln.split("\t")[0] for ln in err_lines} == bad
    for ln in err_lines:
        assert len(ln.split("\t")) == 2   # line_id \t message -- not corrupted/interleaved

    processed = [ln for ln in
                 open(os.path.join(out, "clip-index-processed.txt"), encoding="utf-8")
                 .read().splitlines() if ln]
    assert len(processed) == 30           # every line reached a terminal outcome


def test_extract_parallel_resume_and_limit(tmp_path, monkeypatch):
    """--limit caps NEW work under the pool, and a second run resumes (skips the
    already-done lines) -- no duplicate manifest rows."""
    lines = _fake_lines(20)
    vg = tmp_path / "vg.exe"; vg.write_bytes(b"x")
    out = str(tmp_path / "fw")

    _install_fw_stubs(monkeypatch, lines, jitter=0.001)
    s1 = fx.extract("pkg", out, limit=8, decode=True, vgaudio=str(vg), jobs=4)
    assert s1.ok == 8

    _install_fw_stubs(monkeypatch, lines, jitter=0.001)   # fresh line iterator
    s2 = fx.extract("pkg", out, limit=8, decode=True, vgaudio=str(vg), jobs=4)
    assert s2.skipped >= 8

    ids = [r["line_id"] for r in _read_rows(out)]
    assert len(ids) == len(set(ids)) == 16   # 8 + 8, no dupes


def test_decode_clip_resolves_vgaudio_at_spawn_time_not_import_time(tmp_path, monkeypatch):
    """Regression for issue #25: this test file's `from deciwaves.games.fw import
    extract as fx` (top of file) already imported `fx` long before this test runs, so
    setting DECIWAVES_VGAUDIO here -- after import -- must still be picked up.
    decode_clip's `vgaudio=VGAUDIO` default arg used to freeze the env var at def time
    (module import time), so a later env change was silently ignored; the fix
    re-resolves it at the moment VGAudioCli is actually spawned."""
    monkeypatch.setenv("DECIWAVES_VGAUDIO", r"C:\fake\VGAudioCli.exe")
    seen = []

    class _FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        seen.append(args[0])
        # decode_clip now writes atomically (tmp -> os.replace); the stub must
        # produce the output the real VGAudio would, or the move has nothing to
        # move. `-o <out>` is the last arg.
        with open(args[args.index("-o") + 1], "wb") as f:
            f.write(b"\x00" * 64)
        return _FakeProc()

    monkeypatch.setattr(fx.subprocess, "run", fake_run)
    fx.decode_clip(b"\x00" * 8, str(tmp_path / "out.wav"))
    assert seen == [r"C:\fake\VGAudioCli.exe"], (
        "decode_clip's default vgaudio path must re-resolve DECIWAVES_VGAUDIO at "
        "call time, not freeze it at import/def time")
