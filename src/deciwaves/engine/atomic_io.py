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

The tmp path keeps `dst`'s extension (`name.tmp.ext`, not `name.ext.tmp`):
ffmpeg and vgmstream both infer container/format from the output filename's
extension, so a bare `dst + ".tmp"` (extension-less) makes ffmpeg fail with
"Invalid argument" instead of writing WAV -- keeping the real extension on
the tmp file is what lets it double as the actual subprocess output path.
"""
from __future__ import annotations

import os


def _tmp_path_for(dst):
    root, ext = os.path.splitext(dst)
    return f"{root}.tmp{ext}"


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
        os.replace(tmp, dst)
    except BaseException:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise
