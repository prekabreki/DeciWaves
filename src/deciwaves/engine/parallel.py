"""A small ordered, bounded worker-pool helper for the per-clip decode loops.

Each game's render/extract loop spends nearly all its wall-clock time inside one
decoder subprocess per clip (``vgmstream-cli`` / ``VGAudioCli``) plus the archive
read that feeds it -- both I/O/subprocess-bound, so a thread pool wins big even
under the GIL (the GIL is released across ``subprocess.run`` and blocking file
I/O). :func:`ordered_parallel` runs those per-clip calls concurrently while
handing results back to the *calling* thread in the original input order, so the
caller keeps doing all shared-state bookkeeping (gap accounting, error logging,
manifest/resume appends) single-threaded -- no locks on those files, and output
byte-identical to the old serial loop.

Design points that matter:

* **Ordered.** Results are yielded in input order regardless of which worker
  finishes first, so a manifest/CSV/error file written from the consuming loop is
  identical to the serial run and any "abort on an uncaught exception" happens at
  the same item the serial loop would have hit.
* **Bounded.** At most ``jobs * 2`` items are ever in flight, so a streaming,
  60k-item input (FW extract) never materializes 60k futures at once.
* **jobs<=1 runs inline.** No thread, no pool -- the work runs in the calling
  thread exactly as the pre-#41 serial code did. This is what makes ``--jobs 1``
  a faithful fallback and keeps the existing serial tests exercising the old path.
"""
from __future__ import annotations

import os
import threading
import weakref
from collections import deque
from concurrent.futures import ThreadPoolExecutor


class _LockHandle:
    """A ``threading.Lock`` wrapped in a plain object so it can live in a
    ``weakref.WeakValueDictionary`` -- the bare ``_thread.lock`` objects
    ``threading.Lock()`` returns don't support weak references themselves.
    Acts as its own context manager so ``with locks(key):`` (see
    :class:`KeyedLocks`) is unaffected by the wrapping."""

    __slots__ = ("_lock", "__weakref__")

    def __init__(self):
        self._lock = threading.Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
        return False


class KeyedLocks:
    """A registry handing out one lock per key, created on first use.

    Used to serialize "produce this cache file exactly once" across the decode
    pool: several clips can share one cache output (a DS cutscene track voices
    many lines; two HZD spine items can share a clip_row), so without this two
    workers race to write -- and, worse, one reads the half-written file while
    the other ``os.replace()``s it (a Windows sharing violation, not just wasted
    work). Locking on the output path means the first worker decodes while the
    rest block, then all return the finished cache entry. Distinct outputs get
    distinct locks, so unrelated clips still run fully in parallel.

    The `with locks(key):` holder must re-check the cache after acquiring -- a
    peer may have produced it while we waited.

    Entries are held only WEAKLY (via ``_LockHandle``, above): once every
    caller that was holding or waiting on a given key's lock has exited its
    ``with locks(key):`` block, and nothing else references that lock, it
    becomes eligible for garbage collection -- so a long-running process
    (``engine.audio_clip``'s module-level ``_cache_locks``, reused across
    every clip decoded for the process's whole life) never accumulates one
    permanent lock per distinct cache path it has ever seen. A key currently
    IN USE can never be collected: each caller's own local reference for the
    duration of its `with` block keeps it alive, so mutual exclusion under
    concurrency is unaffected -- only the unbounded growth of finished
    entries is fixed.
    """

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: "weakref.WeakValueDictionary" = weakref.WeakValueDictionary()

    def __call__(self, key) -> _LockHandle:
        with self._guard:
            lk = self._locks.get(key)
            if lk is None:
                lk = self._locks[key] = _LockHandle()
            return lk


def default_jobs() -> int:
    """Sane default worker count: ``min(8, cpu_count)``. Capped at 8 because the
    work is decoder-subprocess-bound -- past a handful of concurrent decoders the
    win flattens and disk/CPU contention starts to cost more than it saves."""
    return min(8, os.cpu_count() or 1)


def ordered_parallel(items, work_fn, jobs):
    """Yield ``work_fn(item)`` for each item in `items`, **in input order**,
    running up to `jobs` calls concurrently in worker threads.

    ``jobs <= 1`` runs each call inline in the calling thread (no pool at all),
    which is exactly the old serial path. Otherwise a bounded window of at most
    ``jobs * 2`` items is kept in flight, so a huge/streaming `items` iterable is
    consumed lazily rather than submitted all at once.

    An exception raised by `work_fn` propagates from the ``yield`` that
    corresponds to the failing item -- i.e. in input order, so a caller that
    stops on the first exception aborts at the same item the serial loop would
    have. Callers that want per-item fail-soft should catch inside `work_fn` and
    return a result record instead of raising.
    """
    if jobs is None or jobs <= 1:
        for item in items:
            yield work_fn(item)
        return

    max_in_flight = jobs * 2
    src = iter(items)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        pending = deque()
        for _ in range(max_in_flight):
            try:
                item = next(src)
            except StopIteration:
                break
            pending.append(ex.submit(work_fn, item))
        while pending:
            result = pending.popleft().result()  # propagates in submission order
            try:
                item = next(src)
            except StopIteration:
                pass
            else:
                pending.append(ex.submit(work_fn, item))
            yield result
