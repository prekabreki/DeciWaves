"""Game-free catalog CSV I/O and resume helpers.

Shared by the per-game catalog stages (``games.ds.catalog``, ``games.hzd.catalog``)
and referenced by ``games.fw.extract``. Deliberately carries no game-specific
knowledge and no heavy dependencies (no ``pydecima``, no ``games.*`` imports), so a
game can reuse the resume bookkeeping without dragging another game's parser in.
"""
from __future__ import annotations

import csv
import os
import tempfile

CSV_COLUMNS = ["line_id", "core_path", "line_index", "category", "scene",
               "speaker_code", "speaker_name", "subtitle_en", "wem_path_en", "language"]


def done_core_paths(csv_path):
    if not os.path.isfile(csv_path):
        return set()
    done = set()
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add(row["core_path"])
    return done


def processed_core_paths(processed_path):
    """Cores that reached a terminal outcome (rows, zero-rows, OR hard-failure). Unlike the CSV,
    this also records cores that parsed to zero rows or failed -- which leave no CSV row and
    would otherwise silently re-run every invocation).

    This is the SOLE resume authority (issue #21): a core's sidecar line is written only
    after all of its rows have been appended to the CSV, so "recorded here" is the only
    signal that a core finished cleanly. Callers must run `prune_incomplete_rows()` first
    so the CSV cannot disagree with it (see that function's docstring)."""
    if not os.path.isfile(processed_path):
        return set()
    with open(processed_path, "r", encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip()}


def prune_incomplete_rows(csv_path, processed_path):
    """Rewrite *csv_path* in place, dropping every row whose ``core_path`` is absent
    from the *processed* sidecar. Returns the number of rows dropped (0 if nothing
    needed pruning -- including when *csv_path* doesn't exist yet).

    Why this exists (issue #21): a core's rows are written per-line but the CSV file
    is only `flush()`-ed once the whole core is done, and the sidecar line for that
    core is written strictly *after* that flush (see games/ds/catalog.py and
    games/hzd/catalog.py). If the process dies mid-core -- after some of its rows made
    it into the CSV but before the sidecar line -- those rows sit in the CSV for a core
    the sidecar never confirmed as finished. Left alone, a plain `done_core_paths(csv)`
    check (or a union of it with the sidecar) would treat that core as done from its
    partial rows alone, silently losing the remainder of its lines forever.

    Call this once at startup, before computing what's "done", so the CSV only ever
    holds rows for cores the sidecar confirms are complete -- making the sidecar the
    single, non-drifting resume authority. The rewrite is atomic (write a temp file,
    then `os.replace()`) so a crash during the prune itself can't corrupt the CSV: the
    original file is left untouched until the replacement is fully written.
    """
    if not os.path.isfile(csv_path):
        return 0
    processed = processed_core_paths(processed_path)
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    kept = [row for row in rows if row["core_path"] in processed]
    dropped = len(rows) - len(kept)
    if dropped == 0:
        return 0
    tmp_path = csv_path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)
    os.replace(tmp_path, csv_path)
    return dropped


def write_core_paths_sidecar(sidecar_path, core_paths) -> None:
    """Atomically persist a catalog stage's resolved core-path list (one path per line),
    so a downstream stage can reuse it instead of repeating the (potentially full-pack)
    scan/harvest that produced it -- see issue #31 (HZD's wem-metadata stage used to
    re-run catalog's whole content scan).

    Written via write-to-a-temp-file-then-``os.replace`` in the sidecar's own directory,
    so a reader (``read_core_paths_sidecar``) never observes a partially-written file --
    it sees either the previous sidecar or the complete new one, never a torn one. On any
    failure the temp file is cleaned up and the exception re-raised; the target path is
    left untouched (either absent, or holding the last complete write).
    """
    out_dir = os.path.dirname(sidecar_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".catalog-cores-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for p in core_paths:
                f.write(p + "\n")
        os.replace(tmp_path, sidecar_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def read_core_paths_sidecar(sidecar_path):
    """Load a core-path sidecar written by ``write_core_paths_sidecar``.

    Returns ``None`` if the sidecar file doesn't exist at all -- the caller decides the
    fallback (e.g. HZD's wem-metadata stage rescans the pack rather than erroring out, so
    it stays usable standalone/without a prior catalog run). An existing-but-empty file
    is a valid "catalog found zero cores" result and returns ``[]`` (not ``None``),
    distinguishing "never ran" from "ran and found nothing."
    """
    if not os.path.isfile(sidecar_path):
        return None
    with open(sidecar_path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]
