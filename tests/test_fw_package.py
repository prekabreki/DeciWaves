# tests/test_fw_package.py
import os
import struct
import lz4.block
import pytest
from pathlib import Path
from deciwaves.engine.pack.base import PackReader
from deciwaves.engine.pack.fw_package import FwPackage
from deciwaves.engine.pack.bin_archive import file_hash

HZD_PACKAGE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package")


def _rtti_walk_len(buf: bytes) -> int:
    """Walk [u64 type][u32 size][size bytes] records; return bytes consumed.
    Returns -1 if a record header runs past the buffer (not a clean RTTI stream)."""
    pos = 0
    n = len(buf)
    while pos < n:
        if pos + 12 > n:
            return -1
        _type, size = struct.unpack_from("<QI", buf, pos)
        pos += 12 + size
        if pos > n:
            return -1
    return pos


def _locator_hash(fw, loc):
    # reverse-lookup the hash for a given Locator (internal map)
    for h, l in fw._locators._by_hash.items():
        if l is loc:
            return h
    raise AssertionError("locator not found")


def test_real_roundtrip_self_verify():
    if not (HZD_PACKAGE / "PackFileLocators.bin").is_file():
        pytest.skip("HZD Remastered install not present")
    fw = FwPackage(str(HZD_PACKAGE))
    loc = fw.first_locator()
    raw = fw.read_by_hash(_locator_hash(fw, loc))
    # 1. exact length: DSAR logical read returned precisely what the locator promised
    assert len(raw) == loc.length
    # 2. RTTI self-verify: the extracted resource walks cleanly to its end
    assert _rtti_walk_len(raw) == len(raw), (
        f"extracted {loc.archive}@{loc.offset} ({loc.length}B) is not a clean RTTI stream")


def _make_package(tmp_path, entries):
    """entries: list of (virtual_path_with_ext, payload_bytes).
    Writes one DSAR archive 'package.00.00.core' holding all payloads back-to-back,
    plus a PackFileLocators.bin indexing each by file_hash(path). Returns package dir.
    """
    pkg = tmp_path / "package"
    pkg.mkdir()
    # one chunk per payload, all LZ4
    descriptors = b""
    blob = b""
    locs = []  # (hash, logical_offset, length)
    logical = 0
    header_size, n = 32, len(entries)
    data_start = header_size + n * 32
    phys = data_start
    for path, payload in entries:
        comp = lz4.block.compress(payload, store_size=False)
        descriptors += struct.pack("<QQIIB7x", logical, phys, len(payload), len(comp), 3)
        blob += comp
        locs.append((file_hash(path), logical, len(payload)))
        logical += len(payload)
        phys += len(comp)
    header = struct.pack("<4sHHIIQ8x", b"DSAR", 3, 1, n, data_start, logical)
    (pkg / "package.00.00.core").write_bytes(header + descriptors + blob)
    # locators: 1 packfile, n records
    name = b"package.00.00.core"
    out = struct.pack("<I", 1) + struct.pack("<I", len(name)) + name + struct.pack("<I", len(locs))
    for h, off, length in locs:
        out += struct.pack("<QII", h, off, length)
    (pkg / "PackFileLocators.bin").write_bytes(out)
    return str(pkg)


def test_fw_package_satisfies_pack_reader(tmp_path):
    pkg = _make_package(tmp_path, [("localized/x/sentences.core", b"core-bytes")])
    assert isinstance(FwPackage(pkg), PackReader)


def test_read_core_roundtrip(tmp_path):
    payload = b"SENTENCES-RESOURCE-" * 50
    pkg = _make_package(tmp_path, [("localized/x/sentences.core", payload),
                                   ("localized/y/other.core", b"other")])
    fw = FwPackage(pkg)
    assert fw.has_core("localized/x/sentences")
    assert fw.read_core("localized/x/sentences") == payload
    assert fw.read("localized/y/other.core") == b"other"


def test_missing_path(tmp_path):
    fw = FwPackage(_make_package(tmp_path, [("a.core", b"a")]))
    assert not fw.has_core("nope/missing")
    with pytest.raises(KeyError):
        fw.read("nope/missing.core")
    with pytest.raises(KeyError):
        fw.read_by_hash(0xDEADBEEF)


def test_first_locator_empty_package(tmp_path):
    fw = FwPackage(_make_package(tmp_path, []))
    with pytest.raises(RuntimeError):
        fw.first_locator()
