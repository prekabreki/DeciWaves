"""Game-free catalog CSV I/O and resume helpers.

Shared by the per-game catalog stages (``games.ds.catalog``, ``games.hzd.catalog``)
and referenced by ``games.fw.extract``. Deliberately carries no game-specific
knowledge and no heavy dependencies (no ``pydecima``, no ``games.*`` imports), so a
game can reuse the resume bookkeeping without dragging another game's parser in.
"""
from __future__ import annotations

import csv
import os

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
