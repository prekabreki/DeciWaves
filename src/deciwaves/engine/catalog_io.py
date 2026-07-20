"""Game-free catalog CSV I/O and resume helpers.

Shared by the per-game catalog stages (``games.ds.catalog``, ``games.hzd.catalog``)
and referenced by ``games.fw.extract``. Deliberately carries no game-specific
knowledge and no heavy dependencies (no ``pydecima``, no ``games.*`` imports), so a
game can reuse the resume bookkeeping without dragging another game's parser in.
"""
from __future__ import annotations

import csv
import os

from deciwaves.engine.atomic_io import atomic_write

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
    so the CSV cannot disagree with it (see that function's docstring).

    IMPORTANT: per-caller failure-recording convention differs.  The ds/hzd catalogs record
    hard per-core parse FAILURES here (permanent, never recoverable).  ``games.fw.extract``
    deliberately does NOT record per-line decode failures in the sidecar (they are expected
    to be transient and retried each run) -- see that module's docstring."""
    if not os.path.isfile(processed_path):
        return set()
    with open(processed_path, "r", encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip()}


def prune_incomplete_rows(csv_path, processed_path, key_column="core_path"):
    """Rewrite *csv_path* in place, dropping every row whose *key_column* value is
    absent from the *processed* sidecar. Returns the number of rows dropped (0 if
    nothing needed pruning -- including when *csv_path* doesn't exist yet).

    *key_column* defaults to ``"core_path"`` (the ds/hzd catalogs' resume key) but
    is overridable: ``games.fw.extract`` reuses this same helper keyed on
    ``"line_id"`` instead of duplicating the prune logic for its own manifest shape
    (issue #43).

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
    single, non-drifting resume authority. The rewrite is atomic (via
    ``engine.atomic_io.atomic_write``: a temp file in the CSV's own directory,
    moved into place with `os.replace()` only once fully written) so a crash during
    the prune itself can't corrupt the CSV: the original file is left untouched
    until the replacement is fully written.

    One case is deliberately NOT pruned (finding 3): the sidecar FILE is entirely
    absent while the CSV holds data rows. An empty ``processed`` set would otherwise
    prune EVERY row -- silently wiping a multi-hour catalog to a bare header. A missing
    sidecar file means the CSV state arrived from elsewhere (a backup, a selective
    copy) rather than being this workspace's own bookkeeping, so the CSV is trusted:
    we warn loudly, reconstruct the sidecar from the CSV's distinct core_paths (self-
    healing the resume state to the old union behavior for exactly this case), and skip
    pruning. A sidecar that EXISTS but is empty is genuine local bookkeeping (e.g. a
    crash before any core finished) and pruning still fires as designed.
    """
    if not os.path.isfile(csv_path):
        return 0
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not os.path.isfile(processed_path):
        if rows:
            distinct = list(dict.fromkeys(row[key_column] for row in rows))
            print(f"WARNING: resume sidecar {processed_path} is missing but {csv_path} "
                  f"has {len(rows)} data row(s) -- treating the CSV as authoritative "
                  f"(looks restored/copied without its sidecar). Reconstructing the "
                  f"sidecar from {len(distinct)} distinct {key_column}(s) and skipping "
                  f"the incomplete-row prune.")
            write_core_paths_sidecar(processed_path, distinct)
        return 0
    processed = processed_core_paths(processed_path)
    kept = [row for row in rows if row[key_column] in processed]
    dropped = len(rows) - len(kept)
    if dropped == 0:
        return 0

    def _write(tmp_path):
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept)

    atomic_write(csv_path, _write)
    return dropped


def write_core_paths_sidecar(sidecar_path, core_paths, header=None) -> None:
    """Atomically persist a catalog stage's resolved core-path list (one path per line),
    so a downstream stage can reuse it instead of repeating the (potentially full-pack)
    scan/harvest that produced it -- see issue #31 (HZD's wem-metadata stage used to
    re-run catalog's whole content scan).

    Written atomically via ``engine.atomic_io.atomic_write`` (a temp file in the
    sidecar's own directory, moved into place with ``os.replace`` only once fully
    written), so a reader (``read_core_paths_sidecar``) never observes a
    partially-written file -- it sees either the previous sidecar or the complete
    new one, never a torn one. On any failure the temp file is cleaned up and the
    exception re-raised; the target path is left untouched (either absent, or
    holding the last complete write).

    ``header``, if given, is written verbatim as the sidecar's first line (expected to
    start with ``#`` so ``read_core_paths_sidecar`` skips it as a comment rather than a
    path -- read it back with ``read_core_paths_sidecar_header``). This module stays
    game-agnostic about what a header means; it's just an optional leading comment line.
    HZD's ``games.hzd.profile.cores_sidecar_header`` uses this to stamp a locators-file
    staleness fingerprint (issue #45). Default (no header) is byte-for-byte the old
    format, so existing sidecars/readers are unaffected.
    """
    out_dir = os.path.dirname(sidecar_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    def _write(tmp_path):
        with open(tmp_path, "w", encoding="utf-8") as f:
            if header is not None:
                f.write(header.rstrip("\n") + "\n")
            for p in core_paths:
                f.write(p + "\n")

    atomic_write(sidecar_path, _write)


def read_core_paths_sidecar(sidecar_path):
    """Load a core-path sidecar written by ``write_core_paths_sidecar``.

    Returns ``None`` if the sidecar file doesn't exist at all -- the caller decides the
    fallback (e.g. HZD's wem-metadata stage rescans the pack rather than erroring out, so
    it stays usable standalone/without a prior catalog run). An existing-but-empty file
    is a valid "catalog found zero cores" result and returns ``[]`` (not ``None``),
    distinguishing "never ran" from "ran and found nothing."

    A leading ``#``-prefixed first line (a header written via ``write_core_paths_sidecar``'s
    ``header=``) is treated as a comment and excluded from the returned paths -- read it
    back separately with ``read_core_paths_sidecar_header``.
    """
    if not os.path.isfile(sidecar_path):
        return None
    with open(sidecar_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return [ln for ln in lines if ln]


def read_core_paths_sidecar_header(sidecar_path):
    """Return the sidecar's leading ``#``-prefixed header/comment line verbatim (as
    written by ``write_core_paths_sidecar``'s ``header=``), or ``None`` if the sidecar
    doesn't exist, is empty, or its first line isn't a comment -- e.g. a legacy sidecar
    written before this feature existed (see games.hzd.wem_metadata's staleness check,
    issue #45)."""
    if not os.path.isfile(sidecar_path):
        return None
    with open(sidecar_path, "r", encoding="utf-8") as f:
        first = f.readline().rstrip("\n")
    return first if first.startswith("#") else None
