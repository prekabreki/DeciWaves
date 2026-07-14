import struct
from deciwaves.games.hzd.clip_index import clip_ab


class _FakeEntry:
    def __init__(self, offset, length): self.offset, self.length = offset, length


class _FakeDsar:
    def __init__(self, header): self._h = header
    def read(self, offset, length): return self._h[:length]


def test_clip_ab_uses_length_and_fact():
    fact = b"fact" + struct.pack("<II", 4, 5300)
    body = b"WAVEfmt " + struct.pack("<I", 16) + b"\x00"*16 + fact
    header = b"RIFF" + struct.pack("<I", len(body)) + body
    a, b = clip_ab(_FakeDsar(header), _FakeEntry(offset=0, length=1000))
    assert a == 1000          # A is the locator length, authoritative
    assert b == 5300          # B from the fact chunk
