"""Synthetic-bytes fixtures for DS:DC's encrypted `.bin` packfile path
(`engine.pack.bin_archive.BinArchive` / `engine.pack.bin_index.PackIndex`).

Models the technique `tests/test_dsar_archive.py` already demonstrates for HZD's
DSAR container: hand-build a byte-exact archive in a tmp dir and exercise the
REAL reader end-to-end -- no mocking of BinArchive/PackIndex.

Coverage split, mirroring the three algorithmic stages named in bin_archive.py's
module docstring ("murmur ... decrypt ... Oodle"):

* murmur -- every test below hashes its virtual paths with the real
  `file_hash()` (MurmurHash3 x64-128, seed 42) to populate the synthetic file
  table, then looks them up by path through `BinArchive.find` / `PackIndex.read`
  -- the same hash function driving both the write and read side, exactly as
  the real game's tooling does (see .memories/hzd-pack-format.md: "the path hash
  reuses the exact same primitive" across both DS and HZD).
* decrypt -- `test_encrypted_archive_round_trips` builds a fully ENCRYPTED
  archive (header + file table + chunk table + chunk data all XOR'd). Building
  valid ciphertext requires the same symmetric XOR transform the decoder uses
  (`_decrypt_block` / `_decrypt_chunk_data` are plain `vals[i] ^= iv` -- self-
  inverse), so this test imports and calls those two module-level helpers
  directly to construct the on-disk bytes, then runs the REAL, un-modified
  `BinArchive.open_index()` / `.extract()` to decrypt them back. This is the
  same "build with the paired transform" technique as test_dsar_archive.py's
  use of `lz4.block.compress` (an independent library there; here, the only
  encoder for this project-specific cipher is the module's own decrypt
  function, since it is its own inverse) -- it is not a mock of the code under
  test: BinArchive itself is never patched, and a header-layout / call-site /
  offset-math bug in `open_index`/`extract` still fails this test. What it
  *cannot* independently catch is a hypothetical bug in the shared XOR/murmur
  math itself -- that still rests on the real-install-gated byte-exact test in
  test_pack_index.py.
* Oodle -- deliberately NOT exercised. Every chunk below stores payload data
  RAW (`compressed_size == uncompressed_size`), which both encrypted and
  unencrypted real archives use for incompressible/small chunks and which
  BinArchive.extract() special-cases to skip Oodle entirely
  (`if c.compressed_size == c.uncompressed_size: buf += bytes(comp)`). This
  sidesteps the missing-Oodle-DLL risk flagged when this issue was scoped, but
  means `oodle_decompress()` itself has no synthetic-bytes coverage here.
"""
import struct

import pytest

from deciwaves.engine.pack import bin_archive
from deciwaves.engine.pack.bin_archive import (
    BinArchive,
    _decrypt_block,
    _decrypt_chunk_data,
    file_hash,
)
from deciwaves.engine.pack.bin_index import PackIndex

MAGIC_PLAIN = 0x20304050
MAGIC_ENCRYPTED = 0x21304050


def _pack_file_entry(entry_num, path_hash, offset, size):
    """Plaintext 8-dword (0x20 byte) file-table record, unencrypted layout.
    e[1]/e[7] (the encryption key halves) are unused when unencrypted -- zero-fill."""
    hash_lo = path_hash & 0xFFFFFFFF
    hash_hi = (path_hash >> 32) & 0xFFFFFFFF
    off_lo = offset & 0xFFFFFFFF
    off_hi = (offset >> 32) & 0xFFFFFFFF
    return struct.pack('<IIIIIIII', entry_num, 0, hash_lo, hash_hi, off_lo, off_hi, size, 0)


def _pack_chunk_entry(uncompressed_offset, uncompressed_size, compressed_offset, compressed_size):
    """Plaintext 8-dword chunk-table record, unencrypted, RAW storage
    (compressed_size == uncompressed_size skips Oodle in BinArchive.extract)."""
    uo_lo = uncompressed_offset & 0xFFFFFFFF
    uo_hi = (uncompressed_offset >> 32) & 0xFFFFFFFF
    co_lo = compressed_offset & 0xFFFFFFFF
    co_hi = (compressed_offset >> 32) & 0xFFFFFFFF
    return struct.pack('<IIIIIIII', uo_lo, uo_hi, uncompressed_size, 0, co_lo, co_hi, compressed_size, 0)


def _write_bin_archive(path, file_entries, chunks):
    """file_entries: list of (entry_num, path_hash, offset, size) -- logical space.
    chunks: list of (uncompressed_offset, payload_bytes) -- stored RAW (no Oodle).
    Lays out an unencrypted (magic 0x20304050) .bin file with key=0."""
    file_table = b"".join(_pack_file_entry(*e) for e in file_entries)
    chunk_table = b""
    chunk_data = b""
    phys_off_base = 0x28 + len(file_table) + 32 * len(chunks)
    phys_off = phys_off_base
    for uncompressed_offset, payload in chunks:
        chunk_table += _pack_chunk_entry(uncompressed_offset, len(payload), phys_off, len(payload))
        chunk_data += payload
        phys_off += len(payload)
    header = struct.pack('<II', MAGIC_PLAIN, 0) + struct.pack(
        '<IIIIIIII', 0, 0, 0, 0, len(file_entries), 0, len(chunks), max((len(p) for _, p in chunks), default=0)
    )
    path.write_bytes(header + file_table + chunk_table + chunk_data)


def test_single_file_single_chunk_round_trip(tmp_path):
    path = "synthetic/lines_pr201/sentences"
    payload = b"DECIMA-SYNTHETIC-PAYLOAD-" * 20
    h = file_hash(path + ".core")
    archive_path = tmp_path / "01_test.bin"
    _write_bin_archive(archive_path, [(0, h, 0, len(payload))], [(0, payload)])

    arc = BinArchive(str(archive_path))
    arc.open_index()
    assert arc.encrypted is False
    assert len(arc.file_table) == 1
    entry = arc.find(path + ".core")
    assert entry is not None
    assert arc.extract(entry, oodle_dll="unused") == payload


def test_extract_spans_two_chunks(tmp_path):
    """Mirrors test_dsar_archive.py's chunk-boundary-crossing case: a single
    file entry whose bytes are split across two RAW-stored chunks."""
    a, b = b"A" * 500, b"B" * 500
    path = "synthetic/spanning_file"
    h = file_hash(path + ".core")
    archive_path = tmp_path / "spanning.bin"
    _write_bin_archive(
        archive_path,
        [(0, h, 0, 1000)],
        [(0, a), (500, b)],
    )
    arc = BinArchive(str(archive_path))
    arc.open_index()
    entry = arc.find(path + ".core")
    assert arc.extract(entry, oodle_dll="unused") == a + b


def test_bad_magic_raises(tmp_path):
    p = tmp_path / "bad.bin"
    p.write_bytes(b"\x00\x00\x00\x00" + b"\x00" * 60)
    arc = BinArchive(str(p))
    with pytest.raises(ValueError, match="bad magic"):
        arc.open_index()


def test_find_by_hash_or_path_agree(tmp_path):
    path = "synthetic/hash_or_path"
    payload = b"X" * 64
    h = file_hash(path + ".core")
    archive_path = tmp_path / "one.bin"
    _write_bin_archive(archive_path, [(0, h, 0, len(payload))], [(0, payload)])
    arc = BinArchive(str(archive_path))
    arc.open_index()
    by_path = arc.find(path + ".core")
    by_hash = arc.find(h)
    assert by_path is by_hash
    assert arc.find("synthetic/does_not_exist.core") is None


# --- PackIndex: multi-archive directory aggregation --------------------------

def test_pack_index_reads_across_multiple_archives(tmp_path):
    path_a = "synthetic/group_a/sentences"
    path_b = "synthetic/group_b/sentences"
    payload_a = b"GROUP-A-" * 10
    payload_b = b"GROUP-B-" * 10
    _write_bin_archive(
        tmp_path / "10_a.bin",
        [(0, file_hash(path_a + ".core"), 0, len(payload_a))],
        [(0, payload_a)],
    )
    _write_bin_archive(
        tmp_path / "20_b.bin",
        [(0, file_hash(path_b + ".core"), 0, len(payload_b))],
        [(0, payload_b)],
    )
    idx = PackIndex(str(tmp_path), oodle_dll="unused")
    assert idx.read_core(path_a) == payload_a
    assert idx.read_core(path_b) == payload_b
    assert idx.has_core(path_a) is True
    assert idx.has_core("synthetic/nope") is False


def test_pack_index_missing_core_raises_keyerror(tmp_path):
    path_a = "synthetic/only_file"
    payload = b"Y" * 32
    _write_bin_archive(
        tmp_path / "01_only.bin",
        [(0, file_hash(path_a + ".core"), 0, len(payload))],
        [(0, payload)],
    )
    idx = PackIndex(str(tmp_path), oodle_dll="unused")
    with pytest.raises(KeyError):
        idx.read_core("synthetic/does_not_exist")


def test_pack_index_first_archive_wins_on_duplicate_hash(tmp_path):
    """bin_index.py: 'first archive wins on duplicate hashes' -- glob is sorted,
    so the alphabetically-first .bin's entry must be the one served."""
    path = "synthetic/duplicate_path"
    h = file_hash(path + ".core")
    first_payload = b"FIRST-WINS-" * 5
    second_payload = b"SECOND-LOSES-" * 5
    _write_bin_archive(tmp_path / "01_first.bin", [(0, h, 0, len(first_payload))], [(0, first_payload)])
    _write_bin_archive(tmp_path / "02_second.bin", [(0, h, 0, len(second_payload))], [(0, second_payload)])

    idx = PackIndex(str(tmp_path), oodle_dll="unused")
    assert idx.read_core(path) == first_payload


# --- Encrypted archive: header + file table + chunk table + chunk data ------

def _encrypt_independent_quad(plain_quad, key):
    """Encrypt a 4-dword block whose key is an INDEPENDENT header field (the
    header's own `key`/`key+1`, not embedded in the block). `_decrypt_block` is
    a pure XOR against a key-derived IV, so it is its own inverse: calling it on
    plaintext yields ciphertext, and BinArchive calling it again on that
    ciphertext (with the same key) yields plaintext back."""
    vals = list(plain_quad)
    _decrypt_block(key, vals, 0)
    return vals


def _encrypt_self_keyed_quad(plain_quad, key_index, key):
    """Encrypt a 4-dword block whose decrypt key is READ FROM the block itself
    (file-table e[1]/e[7], chunk-table c[3]/c[7]) *before* decryption -- so the
    on-disk value at `key_index` must be exactly `key`, unmodified, while the
    other three positions carry the real payload XOR'd by key's IV. (The
    position at key_index becomes discarded post-decrypt garbage in the real
    reader -- nothing ever reads its decrypted value.)"""
    vals = list(plain_quad)
    vals[key_index] = 0  # placeholder; overwritten below regardless of IV
    _decrypt_block(key, vals, 0)
    vals[key_index] = key
    return vals


def test_encrypted_archive_round_trips(tmp_path):
    """Full encrypted path: header, file table, and chunk table are each
    XOR-encrypted (see helpers above), and the chunk's DATA bytes are also
    XOR-encrypted via `_decrypt_chunk_data` keyed off the *decrypted* chunk
    offset/size fields plus the raw on-disk chunk key -- exactly as
    BinArchive.extract() reconstructs it. Storage is RAW (no Oodle)."""
    header_key = 0xCAFEBABE
    path = "synthetic/encrypted_file"
    h = file_hash(path + ".core")
    payload = b"ENCRYPTED-ROUND-TRIP-" * 8

    # -- file table: one entry, key embedded at e[1] (block0) / e[7] (block1) --
    entry_key_a = 0x11111111
    entry_key_b = 0x22222222
    block0 = _encrypt_self_keyed_quad([0, 0, h & 0xFFFFFFFF, (h >> 32) & 0xFFFFFFFF], 1, entry_key_a)
    block1 = _encrypt_self_keyed_quad([0, 0, len(payload), 0], 3, entry_key_b)
    file_table = struct.pack('<IIII', *block0) + struct.pack('<IIII', *block1)

    # -- chunk table: one chunk, RAW storage, key embedded at c[3] / c[7] --
    chunk_key_a = 0x33333333
    chunk_key_b = 0x44444444
    data_start = 0x28 + len(file_table) + 0x20
    plain_c0 = [0, 0, len(payload), 0]              # uncompressed_offset(lo,hi), size, [key slot]
    plain_c1 = [data_start, 0, len(payload), 0]      # compressed_offset(lo,hi), size, [key slot]
    cblock0 = _encrypt_self_keyed_quad(plain_c0, 3, chunk_key_a)
    cblock1 = _encrypt_self_keyed_quad(plain_c1, 3, chunk_key_b)
    chunk_table = struct.pack('<IIII', *cblock0) + struct.pack('<IIII', *cblock1)

    # -- chunk data: XOR'd with the same key_block extract() will reconstruct:
    #    struct.pack('<IIII', c0_decrypted[0], c0_decrypted[1], c0_decrypted[2], ck)
    #    where ck is the RAW on-disk c[3] (== chunk_key_a, since that's what we placed there).
    key_block = struct.pack('<IIII', 0, 0, len(payload), chunk_key_a)
    enc_payload = bytearray(payload)
    _decrypt_chunk_data(key_block, enc_payload)

    # -- header: hv[0:4] arbitrary/unused (fileSize/dataSize), hv[4:8] real --
    hv_plain = [0, 0, 0, 0, 1, 0, 1, len(payload)]  # file_table_count=1, chunk_table_count=1, max_chunk=len
    hv_enc = _encrypt_independent_quad(hv_plain[0:4], header_key) + _encrypt_independent_quad(hv_plain[4:8], header_key + 1)
    header = struct.pack('<II', MAGIC_ENCRYPTED, header_key) + struct.pack('<IIIIIIII', *hv_enc)

    archive_path = tmp_path / "encrypted.bin"
    archive_path.write_bytes(header + file_table + chunk_table + bytes(enc_payload))

    arc = BinArchive(str(archive_path))
    arc.open_index()
    assert arc.encrypted is True
    assert len(arc.file_table) == 1
    entry = arc.file_table[0]
    assert entry.hash == h
    assert entry.offset == 0
    assert entry.size == len(payload)

    assert arc.extract(entry, oodle_dll="unused") == payload


# --- Oodle loader: per-path caching --------------------------------------
#
# _load_oodle can't be exercised against a real oo2core DLL in CI (no game
# install), so ctypes.WinDLL itself is faked -- this only targets the
# caching/argtypes contract, not the real Kraken decompress call.

class _FakeOodleLib:
    def __init__(self, dll_path):
        self.dll_path = dll_path
        self.OodleLZ_Decompress = lambda *a, **k: 0


@pytest.fixture(autouse=True)
def _reset_oodle_cache(monkeypatch):
    """Every test in this module gets a clean, isolated Oodle DLL cache --
    without this, whichever test runs first would permanently poison the
    real module-level cache for every later test (and any other test file
    importing bin_archive in the same process)."""
    monkeypatch.setattr(bin_archive, "_oodle_cache", {})


def test_load_oodle_caches_per_dll_path(monkeypatch):
    """A second _load_oodle call with a DIFFERENT dll_path must load its OWN
    DLL, not silently reuse whatever was cached for the first path."""
    constructed = []

    def _fake_windll(path):
        constructed.append(path)
        return _FakeOodleLib(path)

    monkeypatch.setattr(bin_archive.ctypes, "WinDLL", _fake_windll)

    lib_a = bin_archive._load_oodle("path_a.dll")
    lib_b = bin_archive._load_oodle("path_b.dll")

    assert constructed == ["path_a.dll", "path_b.dll"]  # one WinDLL() call per distinct path
    assert lib_a is not lib_b
    assert lib_a.dll_path == "path_a.dll"
    assert lib_b.dll_path == "path_b.dll"


def test_load_oodle_reuses_same_dll_path(monkeypatch):
    """Calling _load_oodle twice with the SAME path must not reload the DLL."""
    constructed = []

    def _fake_windll(path):
        constructed.append(path)
        return _FakeOodleLib(path)

    monkeypatch.setattr(bin_archive.ctypes, "WinDLL", _fake_windll)

    lib_1 = bin_archive._load_oodle("same.dll")
    lib_2 = bin_archive._load_oodle("same.dll")

    assert constructed == ["same.dll"]  # loaded once
    assert lib_1 is lib_2


def test_load_oodle_declares_argtypes(monkeypatch):
    """OodleLZ_Decompress.argtypes must be explicitly declared (not left to
    ctypes' fragile default int marshalling) alongside its .restype."""
    monkeypatch.setattr(bin_archive.ctypes, "WinDLL", lambda path: _FakeOodleLib(path))

    lib = bin_archive._load_oodle("argtypes.dll")

    assert lib.OodleLZ_Decompress.argtypes is not None
    assert len(lib.OodleLZ_Decompress.argtypes) == 14  # matches the 14-arg call in oodle_decompress()
