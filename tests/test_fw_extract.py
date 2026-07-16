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
        return _FakeProc()

    monkeypatch.setattr(fx.subprocess, "run", fake_run)
    fx.decode_clip(b"\x00" * 8, str(tmp_path / "out.wav"))
    assert seen == [r"C:\fake\VGAudioCli.exe"], (
        "decode_clip's default vgaudio path must re-resolve DECIWAVES_VGAUDIO at "
        "call time, not freeze it at import/def time")
