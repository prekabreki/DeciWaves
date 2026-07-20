"""Shared atomic-write helper for cached derived files (WAVs, trims, etc).

Every cached-write site in this codebase used to follow check-then-produce:
decode/encode straight to the final cache path, then rely on a later
`isfile`/`getsize` check to decide whether the cache is valid. ffmpeg,
`wave`, and vgmstream all write incrementally, so an interruption partway
through (Ctrl-C, a crash, a killed process) leaves a truncated file sitting
at that final path -- and every later run's cache check happily treats it as
valid forever, producing silently corrupted audio downstream.

`atomic_write` closes that gap: the producer writes to a temp path *in the
same directory* as the destination (so the final move is an atomic
same-volume rename via `os.replace`, not a cross-volume copy -- this matters
on Windows), and the destination only ever comes into existence via that
final `os.replace()`. Any interruption or failure before that point leaves
`dst` untouched (a prior valid cache entry, if any, survives) and removes the
partial tmp file so it doesn't linger.

The tmp path keeps `dst`'s extension (`name.tmp.<token>.ext`, not
`name.ext.tmp`): ffmpeg and vgmstream both infer container/format from the
output filename's extension, so a bare `dst + ".tmp"` (extension-less) makes
ffmpeg fail with "Invalid argument" instead of writing WAV -- keeping the real
extension on the tmp file is what lets it double as the actual subprocess
output path.

The tmp name also carries a unique random token, so it is collision-proof
*under concurrency*: when the per-clip decode loops run in a worker pool (see
`engine.parallel`), two workers can legitimately target the same cache `dst` at
once (two DS lines sharing one cutscene stream, two HZD spine items sharing one
clip_row). A deterministic tmp name would make both write the same tmp file and
`os.replace()` it out from under each other; a per-call random token means each
worker owns its own tmp and the last `os.replace` simply wins with identical
bytes.
"""
from __future__ import annotations

import os
import time
import uuid


def _tmp_path_for(dst):
    root, ext = os.path.splitext(dst)
    return f"{root}.tmp.{uuid.uuid4().hex}{ext}"


def _stat_sig(path):
    """`(size, mtime_ns)` for *path*, or ``None`` if it doesn't exist. A cheap
    signature for "did this file change out from under us" without hashing."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _replace(tmp, dst, attempts=100, delay=0.005):
    """`os.replace(tmp, dst)`, tolerating a concurrent writer racing on the same
    `dst`.

    On Windows two threads replacing the same destination at once can hit a
    transient sharing violation (``PermissionError``/``FileNotFoundError``) even
    though each owns a distinct tmp file. For the decode-cache callers every
    writer of a given cache path produces identical bytes (the source ->
    decoded-output mapping is deterministic), so a peer that already put a NEW
    file at `dst` has done our job for us: on failure we can discard our
    redundant tmp and return.  CAUTION: three #51 callers (``config.save``,
    ``prune_incomplete_rows``, ``write_core_paths_sidecar``) produce DIFFERENT
    bytes per writer, so a peer's "win" silently last-writer-wins drops our
    write (the reviewer judged this defensible for those writes).

    The catch (finding 7): `dst` existing on failure is not proof a peer won.
    `dst` may be the stale/invalid file the caller is REWRITING (e.g. the
    <=44-byte WAV stub `audio_clip` deliberately regenerates) -- returning early
    there discarded the fresh tmp and left the stale bytes in place forever, with
    the 100-attempt retry loop never running. So we capture `dst`'s stat
    signature at entry and treat "peer won" as valid only if `dst` did not exist
    at entry, or its signature has CHANGED since (a genuinely new file appeared).
    An unchanged pre-existing `dst` means no peer intervened: keep retrying (and
    raise after exhaustion) so our fresh bytes replace the stale ones.
    """
    entry_sig = _stat_sig(dst)
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except OSError:
            cur_sig = _stat_sig(dst)
            if cur_sig is not None and cur_sig != entry_sig:  # a peer wrote a NEW file
                if os.path.isfile(tmp):
                    os.remove(tmp)
                return
            if i == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write(dst, write_fn):
    """Produce `dst` atomically.

    Calls `write_fn(tmp_path)`, which must write the complete file to
    `tmp_path` (raising on failure). Only once `write_fn` returns
    successfully is `tmp_path` moved into place at `dst` via `os.replace`.
    `tmp_path` lives beside `dst` (same directory) and keeps its extension,
    so it is itself a valid target for tools (ffmpeg, vgmstream) that infer
    output format from the filename.

    On any exception from `write_fn` (including `KeyboardInterrupt` / a
    mid-stream crash), the partial `tmp_path` is removed if present and the
    exception is re-raised -- `dst` is never touched, so an existing valid
    cache entry is never clobbered and a missing one is never poisoned with
    partial data.
    """
    tmp = _tmp_path_for(dst)
    try:
        write_fn(tmp)
        _replace(tmp, dst)
    except BaseException:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise
