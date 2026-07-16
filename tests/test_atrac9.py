import struct

from deciwaves.games.hzd import atrac9
from deciwaves.games.hzd.atrac9 import fact_sample_count, trim_riff


def _riff_with_fact(sample_count):
    fact = b"fact" + struct.pack("<II", 4, sample_count)
    body = b"WAVEfmt " + struct.pack("<I", 16) + b"\x00" * 16 + fact
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_fact_sample_count_parsed():
    assert fact_sample_count(_riff_with_fact(7098624)) == 7098624


def test_fact_absent_returns_none():
    assert fact_sample_count(b"RIFF\x08\x00\x00\x00WAVEfmt ") is None


def test_trim_riff_cuts_trailing():
    data = _riff_with_fact(10) + b"GARBAGE_TAIL"
    assert trim_riff(data) == data[: struct.unpack("<I", data[4:8])[0] + 8]


def test_decode_wem_to_wav_resolves_vgaudio_at_spawn_time_not_import_time(tmp_path, monkeypatch):
    """Regression for issue #25: this test file's `from deciwaves.games.hzd.atrac9
    import ...` (top of file) already imported `atrac9` long before this test runs, so
    setting DECIWAVES_VGAUDIO here -- after import -- must still be picked up.
    atrac9's module-level `VGAUDIO` constant used to freeze the env var at import
    time, so a later env change was silently ignored; the fix re-resolves it at the
    moment VGAudioCli is actually spawned."""
    monkeypatch.setenv("DECIWAVES_VGAUDIO", r"C:\fake\VGAudioCli.exe")
    seen = []

    class _FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        seen.append(args[0])
        return _FakeProc()

    monkeypatch.setattr(atrac9.subprocess, "run", fake_run)
    wem = _riff_with_fact(10)
    atrac9.decode_wem_to_wav(wem, str(tmp_path / "out.wav"))
    assert seen == [r"C:\fake\VGAudioCli.exe"], (
        "decode_wem_to_wav must re-resolve DECIWAVES_VGAUDIO at call time, not "
        "freeze it into a module-level constant at import time")
