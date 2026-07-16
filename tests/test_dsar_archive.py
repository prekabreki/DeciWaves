import os
import re
import struct
import lz4.block
import pytest
from pathlib import Path
from deciwaves.engine.pack.dsar_archive import DsarArchive


def _write_dsar(tmp_path, chunks):
    """chunks: list of (uncompressed_payload, store_uncompressed: bool).
    Lays out a valid DSAR v3.1 file and returns its path. total_size = sum of payloads.
    """
    n = len(chunks)
    header_size = 32
    table_size = n * 32
    data_start = header_size + table_size
    descriptors = b""
    blob = b""
    logical_off = 0
    phys_off = data_start
    total = sum(len(p) for p, _ in chunks)
    for payload, store_raw in chunks:
        comp = payload if store_raw else lz4.block.compress(payload, store_size=False)
        size = len(payload)
        csize = len(comp)
        descriptors += struct.pack("<QQIIB7x", logical_off, phys_off, size, csize, 3)
        blob += comp
        logical_off += size
        phys_off += csize
    header = struct.pack("<4sHHIIQ8x", b"DSAR", 3, 1, n, data_start, total)
    path = tmp_path / "test.core"
    path.write_bytes(header + descriptors + blob)
    return str(path)


def test_read_single_lz4_chunk(tmp_path):
    payload = b"HELLO-DECIMA-" * 100
    arc = DsarArchive(_write_dsar(tmp_path, [(payload, False)]))
    assert arc.total_size == len(payload)
    assert arc.read(0, len(payload)) == payload
    assert arc.read(13, 20) == payload[13:33]


def test_read_spanning_two_chunks(tmp_path):
    a, b = b"A" * 500, b"B" * 500
    arc = DsarArchive(_write_dsar(tmp_path, [(a, False), (b, False)]))
    assert arc.read(0, 1000) == a + b
    assert arc.read(480, 40) == a[480:] + b[:20]   # crosses the boundary


def test_read_uncompressed_chunk(tmp_path):
    payload = b"\x00\x01\x02\x03" * 64
    arc = DsarArchive(_write_dsar(tmp_path, [(payload, True)]))   # stored raw
    assert arc.read(0, len(payload)) == payload


def test_bad_magic_raises(tmp_path):
    p = tmp_path / "bad.core"
    p.write_bytes(b"XXXX" + b"\x00" * 60)
    with pytest.raises(ValueError, match="DSAR"):
        DsarArchive(str(p))


def test_read_before_first_chunk_raises_not_last_chunk_garbage(tmp_path):
    """A negative (out-of-range) offset finds no containing chunk: _first_chunk
    returns -1. Before the fix, Python negative-indexing `self._chunks[-1]` served
    bytes from the LAST chunk instead of erroring -- assert it raises and names
    the archive path, not that it silently returns data from the wrong chunk."""
    a, b = b"A" * 500, b"B" * 500
    path = _write_dsar(tmp_path, [(a, False), (b, False)])
    arc = DsarArchive(path)
    with pytest.raises(ValueError, match=re.escape(path)):
        arc.read(-5, 10)


def test_read_past_eof_raises_not_silent_truncation(tmp_path):
    """A read whose offset+length runs past the archive's last chunk must raise,
    not silently return a short (truncated) result."""
    a, b = b"A" * 500, b"B" * 500
    path = _write_dsar(tmp_path, [(a, False), (b, False)])
    arc = DsarArchive(path)
    with pytest.raises(ValueError, match=re.escape(path)):
        arc.read(10_000, 10)   # well past total_size (1000)
    with pytest.raises(ValueError, match=re.escape(path)):
        arc.read(990, 20)      # starts in range but crosses EOF


# Override with DECIWAVES_HZD_PACKAGE, mirroring the DECIWAVES_DS_INSTALL /
# DECIWAVES_FW_INSTALL convention (see conftest.py) -- HZD had no such override
# before this, every test hardcoding the same personal Steam path.
HZD_PACKAGE = Path(os.environ.get(
    "DECIWAVES_HZD_PACKAGE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"))


def test_real_dsar_header():
    core = HZD_PACKAGE / "package.00.00.core"
    if not core.is_file():
        pytest.skip("HZD Remastered install not present")
    arc = DsarArchive(str(core))
    assert arc.total_size > 0
    assert len(arc._chunks) > 0
    # the smallest logical offset must be 0 (first chunk covers the start)
    assert arc._chunks[0].offset == 0
