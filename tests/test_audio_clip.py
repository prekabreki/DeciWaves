import math
import os
import shutil
import struct
import wave

import pytest

from deciwaves.engine import audio_clip as ac
from conftest import require_install, DATA_DIR, OODLE_DLL  # noqa: F401

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed")

needs_vgmstream = pytest.mark.skipif(
    not (os.environ.get("DECIWAVES_VGMSTREAM") or shutil.which("vgmstream-cli")),
    reason="vgmstream-cli not found")


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


@needs_vgmstream
def test_clip_wav_decodes_one_real_line(require_install, tmp_path):  # noqa: F811
    from deciwaves.engine.pack.bin_index import PackIndex
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
    """Changing trim params must not return the previously-cached trim. The cache key
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


class _FakeIdxRaw:
    """idx.read() returning a minimal valid RIFF stream, so clip_wav gets far
    enough to invoke the (mocked) vgmstream subprocess."""

    def read(self, p):
        payload = b"WAVE" + b"\x00" * 16
        return b"RIFF" + struct.pack("<I", len(payload)) + payload


class _FakeProc:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_clip_wav_error_includes_exit_code_and_hex_for_ntstatus_range(tmp_path, monkeypatch):
    # 0xC0000135 (STATUS_DLL_NOT_FOUND) is the real-world failure this guards:
    # a Windows Store Python's virtualized child process can't find vgmstream's
    # side-by-side DLLs, so vgmstream-cli dies with this NTSTATUS and empty stderr.
    monkeypatch.setattr(ac.subprocess, "run",
                        lambda *a, **k: _FakeProc(3221225781, stderr=""))
    with pytest.raises(ac.ClipError) as exc:
        ac.clip_wav(_FakeIdxRaw(), "some/stream.core.stream", str(tmp_path),
                    vgmstream="vgmstream-cli")
    msg = str(exc.value)
    assert "exit code 3221225781" in msg
    assert "0xC0000135" in msg
    assert "stderr" not in msg  # empty stderr -> clause omitted entirely


def test_clip_wav_error_includes_stderr_clause_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(ac.subprocess, "run",
                        lambda *a, **k: _FakeProc(1, stderr="missing sample rate"))
    with pytest.raises(ac.ClipError) as exc:
        ac.clip_wav(_FakeIdxRaw(), "some/stream.core.stream", str(tmp_path),
                    vgmstream="vgmstream-cli")
    msg = str(exc.value)
    assert "exit code 1" in msg
    assert "0x" not in msg  # below the NTSTATUS-range threshold -> plain decimal only
    assert "stderr: missing sample rate" in msg


def test_clip_wav_interrupted_vgmstream_does_not_poison_cache(tmp_path, monkeypatch):
    """Regression for issue #18: a vgmstream run that partially writes the
    output then fails (simulating Ctrl-C / a crash mid-decode) must not leave
    a truncated .wav sitting at the FINAL cache path -- clip_wav's own
    `isfile and getsize > 44` check would otherwise treat that truncated file
    as a valid cache hit on every later run, silently serving corrupt audio."""
    def fake_run(args, **kwargs):
        out_path = args[args.index("-o") + 1]
        # >44 bytes: would pass clip_wav's own cache-validity check if it
        # ever ended up at the real cache path.
        with open(out_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 60)
        return _FakeProc(1, stderr="simulated crash mid-decode")

    monkeypatch.setattr(ac.subprocess, "run", fake_run)

    with pytest.raises(ac.ClipError):
        ac.clip_wav(_FakeIdxRaw(), "some/stream.core.stream", str(tmp_path),
                    vgmstream="vgmstream-cli")

    wav_path = os.path.join(str(tmp_path), ac._key("some/stream.core.stream") + ".wav")
    assert not os.path.isfile(wav_path), \
        "failed decode must not poison the WAV cache at the final path"
    assert os.listdir(str(tmp_path)) == [], \
        "no tmp .wav or .wem should be left behind after a failed decode"


@needs_ffmpeg
def test_apply_keep_spans_interrupted_write_does_not_poison_cache(tmp_path, monkeypatch):
    """Regression for issue #18: an atrim-concat run that partially writes the
    destination then fails must not leave a truncated file at the cache path
    that a later run's `isfile and getsize > 44` check would accept."""
    src = tmp_path / "track.wav"
    _synth(src, [("tone", 5.0)])
    cache_dir = tmp_path / "kept"

    real_run = ac.subprocess.run

    def flaky_run(args, **kwargs):
        out_path = args[-1]  # ffmpeg output path is the last arg
        with open(out_path, "wb") as f:
            f.write(b"GARBAGE-NOT-REALLY-A-WAV-FILE-BUT-OVER-44-BYTES-LONG")
        return _FakeProc(1, stderr="simulated ffmpeg crash mid-write")

    monkeypatch.setattr(ac.subprocess, "run", flaky_run)
    with pytest.raises(ac.ClipError):
        ac.apply_keep_spans(str(src), [(1.0, 2.0)], str(cache_dir))

    assert not os.path.isdir(cache_dir) or os.listdir(cache_dir) == [], \
        "failed atrim-concat must not poison the cache with a truncated file"

    # Cache must not be permanently poisoned: a real, successful run afterwards
    # must still work (no leftover .tmp blocking/confusing later writes).
    monkeypatch.setattr(ac.subprocess, "run", real_run)
    out, dur = ac.apply_keep_spans(str(src), [(1.0, 2.0)], str(cache_dir))
    assert os.path.isfile(out)
    assert abs(dur - 1.0) < 0.1


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


def test_clip_wav_resolves_vgmstream_at_spawn_time_not_import_time(tmp_path, monkeypatch):
    """Regression for issue #25: this test file's `from deciwaves.engine import
    audio_clip as ac` (top of file) already imported `ac` long before this test runs,
    so setting DECIWAVES_VGMSTREAM here -- after import -- must still be picked up.
    clip_wav's `vgmstream=VGMSTREAM` default arg used to freeze the env var at def
    time (module import time), so a later env change was silently ignored; the fix
    re-resolves it at the moment vgmstream-cli is actually spawned."""
    monkeypatch.setenv("DECIWAVES_VGMSTREAM", r"C:\fake\vgmstream-cli.exe")
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[0])
        return _FakeProc(1, stderr="simulated failure; only checking argv[0]")

    monkeypatch.setattr(ac.subprocess, "run", fake_run)
    with pytest.raises(ac.ClipError):
        ac.clip_wav(_FakeIdxRaw(), "some/stream.core.stream", str(tmp_path))
    assert seen == [r"C:\fake\vgmstream-cli.exe"], (
        "clip_wav's default vgmstream path must re-resolve DECIWAVES_VGMSTREAM at "
        "call time, not freeze it at import/def time")
