"""DsarArchive decompressed-chunk LRU (issue #50, audit item M17).

The #41 decode pools share ONE DsarArchive across N threads and issue many small
reads that each fall inside a large LZ4 chunk (e.g. clip_index reads a 2 KB
header out of a 256 KB chunk). Without a cache each read re-decompresses the
whole covering chunk. These tests pin:

  * the cache actually elides redundant decompression (behavioural RED),
  * bytes are identical cached vs cold, including boundary-spanning reads,
  * concurrent readers over overlapping ranges always get correct bytes
    (a wrong-bytes race is the one unacceptable failure),
  * the cache is bounded (LRU eviction never corrupts a later read).
"""
import threading

import lz4.block
import pytest

from deciwaves.engine.pack.dsar_archive import DsarArchive

# byte-exact DSAR writer already used by the sibling test module
from test_dsar_archive import _write_dsar


def _count_decompress(monkeypatch):
    calls = {"n": 0}
    real = lz4.block.decompress

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(lz4.block, "decompress", counting)
    return calls


def test_shared_chunk_decompressed_once_per_chunk(tmp_path, monkeypatch):
    """Four reads touching only two chunks must decompress two times, not four."""
    a, b = b"A" * 500, b"B" * 500          # each compresses well -> real decompress
    arc = DsarArchive(_write_dsar(tmp_path, [(a, False), (b, False)]))
    calls = _count_decompress(monkeypatch)

    assert arc.read(0, 10) == a[:10]
    assert arc.read(100, 10) == a[100:110]   # same chunk 0 -> cache hit
    assert arc.read(600, 10) == b[100:110]   # chunk 1 -> one decompress
    assert arc.read(700, 10) == b[200:210]   # same chunk 1 -> cache hit

    assert calls["n"] == 2                    # one decompress per distinct chunk


def test_bytes_identical_cached_vs_cold(tmp_path):
    payloads = [b"HELLO-" * 200, b"WORLD-" * 200, b"DECIMA" * 200]
    full = b"".join(payloads)
    path = _write_dsar(tmp_path, [(p, False) for p in payloads])

    warm = DsarArchive(path)
    # warm the cache with a first sweep, then re-read and cross-check a cold arc
    for off, length in [(0, 50), (600, 50), (1150, 100), (0, len(full))]:
        warm.read(off, length)

    cold = DsarArchive(path)
    cases = [
        (0, 10),                 # start of chunk 0
        (100, 300),              # within chunk 0
        (1150, 120),             # spans chunk 0 -> chunk 1 boundary (chunk 0 = 1200 B)
        (2350, 130),             # spans chunk 1 -> chunk 2
        (0, len(full)),          # whole archive, all chunks
    ]
    for off, length in cases:
        got_warm = warm.read(off, length)   # served partly/entirely from cache
        assert got_warm == cold.read(off, length)
        assert got_warm == full[off:off + length]


def test_thread_hammer_overlapping_ranges(tmp_path):
    payloads = [bytes([i]) * 4096 for i in range(1, 17)]   # 16 chunks x 4 KiB
    full = b"".join(payloads)
    arc = DsarArchive(_write_dsar(tmp_path, [(p, False) for p in payloads]))

    n_threads = 16
    reads_per_thread = 200
    barrier = threading.Barrier(n_threads)
    errors = []

    def worker(tid):
        rng = __import__("random").Random(tid)
        barrier.wait()   # release together -> maximise cold-cache contention
        for _ in range(reads_per_thread):
            off = rng.randrange(0, len(full) - 1)
            length = rng.randint(1, min(9000, len(full) - off))   # often spans chunks
            got = arc.read(off, length)
            if got != full[off:off + length]:
                errors.append((tid, off, length))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"wrong bytes under concurrency: {errors[:5]}"


def test_cache_is_bounded(tmp_path):
    payloads = [bytes([i]) * 1000 for i in range(1, 8)]   # 7 chunks
    full = b"".join(payloads)
    arc = DsarArchive(_write_dsar(tmp_path, [(p, False) for p in payloads]))
    arc._CACHE_MAX = 2                                     # force heavy eviction

    for i in range(7):                                     # touch every chunk in turn
        off = i * 1000
        assert arc.read(off, 1000) == full[off:off + 1000]
        assert len(arc._chunk_cache) <= 2                  # never grows past the cap

    # a re-read after eviction still returns correct bytes (evicted -> re-decompressed)
    assert arc.read(0, 1000) == payloads[0]
