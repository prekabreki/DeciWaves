import struct
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
