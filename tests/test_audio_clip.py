import math
import shutil
import struct
import wave

import pytest

from engine import audio_clip as ac
from conftest import require_install, DATA_DIR, OODLE_DLL  # noqa: F401

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed")


def _synth(path, segments, sr=48000):
    """Write a mono 48k wav from [(kind, seconds), ...] where kind is
    'tone' (audible sine) or 'silence' (zeros)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for kind, secs in segments:
            n = int(secs * sr)
            if kind == "tone":
                frames = b"".join(
                    struct.pack("<h", int(16000 * math.sin(2 * math.pi * 220 * i / sr)))
                    for i in range(n))
            else:
                frames = b"\x00\x00" * n
            w.writeframes(frames)


def test_trim_riff_cuts_to_declared_size_plus_8():
    payload = b"WAVE" + b"\x00" * 20
    size = len(payload)
    data = b"RIFF" + struct.pack("<I", size) + payload + b"TRAILINGGARBAGE"
    out = ac.trim_riff(data)
    assert len(out) == size + 8 and b"GARBAGE" not in out


def test_trim_riff_rejects_non_riff():
    try:
        ac.trim_riff(b"NOPE" + b"\x00" * 8)
        assert False, "expected ClipError"
    except ac.ClipError:
        pass


def test_wav_duration_seconds(tmp_path):
    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 48000)
    assert abs(ac.wav_duration_seconds(str(p)) - 1.0) < 1e-6


def test_clip_wav_decodes_one_real_line(require_install, tmp_path):
    from engine.pack.bin_index import PackIndex
    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    stream = ("localized/sentences/ds_lines_terminal/lines_pr201/"
              "sentences_sentence_d86c8bae-6aa0-4e37-b3c5-04ddd8d447f8"
              ".wem.english.core.stream")
    wav, dur = ac.clip_wav(idx, stream, str(tmp_path))
    assert wav.endswith(".wav") and dur > 0


@needs_ffmpeg
def test_trim_collapses_long_silence(tmp_path):
    src = tmp_path / "long.wav"
    _synth(src, [("tone", 2), ("silence", 30), ("tone", 2)])  # 34 s
    out, dur = ac.trim_long_silences(str(src), str(tmp_path / "trim"),
                                     min_silence=10.0, keep=0.75)
    # 30 s gap (>=10 s) collapses to ~0.75 s: 2 + 0.75 + 2 = ~4.75 s
    assert dur < 8.0, f"long silence not trimmed (dur={dur})"
    assert abs(dur - 4.75) < 0.8, f"unexpected trimmed dur={dur}"


@needs_ffmpeg
def test_trim_keeps_short_silence(tmp_path):
    src = tmp_path / "short.wav"
    _synth(src, [("tone", 2), ("silence", 5), ("tone", 2)])  # 9 s, gap < 10 s
    out, dur = ac.trim_long_silences(str(src), str(tmp_path / "trim"),
                                     min_silence=10.0, keep=0.75)
    assert abs(dur - 9.0) < 0.5, f"short silence should be kept (dur={dur})"


@needs_ffmpeg
def test_trim_no_silence_unchanged(tmp_path):
    src = tmp_path / "nosil.wav"
    _synth(src, [("tone", 3)])
    out, dur = ac.trim_long_silences(str(src), str(tmp_path / "trim"),
                                     min_silence=10.0, keep=0.75)
    assert abs(dur - 3.0) < 0.3, f"clip with no long silence changed (dur={dur})"


@needs_ffmpeg
def test_trim_param_change_not_stale_cached(tmp_path):
    """Changing trim params must not return the previously-cached trim (#42). The cache key
    folds min_silence/threshold_db/keep, so re-running the same source with a larger `keep`
    re-trims to a longer clip instead of silently reusing the shorter cached result."""
    src = tmp_path / "gap.wav"
    _synth(src, [("tone", 2), ("silence", 30), ("tone", 2)])   # 34 s, one long gap
    cache = str(tmp_path / "trim")
    out1, dur1 = ac.trim_long_silences(str(src), cache, min_silence=10.0, keep=0.75)
    out2, dur2 = ac.trim_long_silences(str(src), cache, min_silence=10.0, keep=5.0)
    assert abs(dur1 - 4.75) < 0.8, f"keep=0.75 gap collapses to ~0.75 s (dur={dur1})"
    assert abs(dur2 - 9.0) < 0.8, f"keep=5.0 must re-trim, not reuse stale dur1 (dur={dur2})"
    assert out1 != out2, "different trim params must map to different cache files"


@needs_ffmpeg
def test_apply_keep_spans_duration_is_sum_of_spans(tmp_path):
    src = tmp_path / "track.wav"
    _synth(src, [("tone", 10.0)])
    out, dur = ac.apply_keep_spans(str(src), [(1.0, 2.0), (5.0, 7.0)],
                                    str(tmp_path / "kept"))
    assert abs(dur - 3.0) < 0.1  # 1s + 2s


@needs_ffmpeg
def test_apply_keep_spans_caches_by_spans(tmp_path):
    src = tmp_path / "track.wav"
    _synth(src, [("tone", 5.0)])
    a, _ = ac.apply_keep_spans(str(src), [(0.0, 1.0)], str(tmp_path / "kept"))
    b, _ = ac.apply_keep_spans(str(src), [(0.0, 2.0)], str(tmp_path / "kept"))
    assert a != b  # different spans -> different cached file, not a stale hit


def test_apply_keep_spans_empty_raises(tmp_path):
    with pytest.raises(ac.ClipError):
        ac.apply_keep_spans(str(tmp_path / "x.wav"), [], str(tmp_path / "kept"))


def test_clip_wav_cleans_temp_wem_when_vgmstream_missing(tmp_path):
    import os
    class FakeIdx:
        def read(self, p):
            payload = b"WAVE" + b"\x00" * 16
            return b"RIFF" + struct.pack("<I", len(payload)) + payload + b"XXXX"
    try:
        ac.clip_wav(FakeIdx(), "some/stream.core.stream", str(tmp_path),
                    vgmstream=str(tmp_path / "does_not_exist.exe"))
    except Exception:
        pass  # FileNotFoundError or ClipError both acceptable
    leftover = [f for f in os.listdir(tmp_path) if f.endswith(".wem")]
    assert leftover == [], f"temp .wem leaked: {leftover}"
