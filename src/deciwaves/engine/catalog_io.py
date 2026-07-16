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
    would otherwise silently re-run every invocation)."""
    if not os.path.isfile(processed_path):
        return set()
    with open(processed_path, "r", encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip()}


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
