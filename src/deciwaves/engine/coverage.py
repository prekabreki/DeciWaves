"""Persisted per-stage coverage summaries (issue #63, GUI spec §5.4).

Coverage and cap-skip numbers used to be computed and then thrown away as
stdout messages -- so a ``--sample-cap``'d rip was indistinguishable ON DISK
from a complete one, and anything wanting the numbers (the GUI coverage bar)
had to scrape stdout. Each stage that computes such numbers now also merges
them, as its own section keyed by stage name, into one per-game JSON artifact
(``out/<game>/coverage.json``).

Game-agnostic by the same rule as the rest of ``engine/``: this module knows
how to merge-and-persist a stage's stats dict; WHAT the stats are is each
stage's own business (see games/hzd/wem_metadata.py and asr_bind.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from deciwaves.engine.atomic_io import atomic_write


def default_coverage_path(game: str) -> str:
    """Workspace-relative location of a game's coverage artifact -- the path
    the GUI reads, and every stage's ``--coverage-out`` default."""
    return os.path.join("out", game, "coverage.json")


def write_stage_coverage(path: str, stage: str, stats: dict) -> None:
    """Merge ``stats`` into the JSON artifact at ``path`` as section ``stage``,
    creating the file (and parent dirs) if needed.

    Read-modify-write with an atomic replace: stages run as separate,
    sequential processes, each owning one section -- an earlier stage's
    section survives a later stage's write, and a re-run stage replaces its
    own section wholesale (no stale keys from an older schema linger). A
    corrupt or non-object existing file is derived data, so it is rebuilt
    from scratch rather than crashing the stage -- but never silently.
    """
    try:
        existing = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warning: {path} is corrupted ({exc}); rebuilding it")
        existing = {}
    if not isinstance(existing, dict):
        print(f"warning: {path} held {type(existing).__name__}, not a JSON "
              f"object; rebuilding it")
        existing = {}
    existing[stage] = stats
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    atomic_write(path, lambda tmp: Path(tmp).write_text(
        json.dumps(existing, indent=2) + "\n", encoding="utf-8"))
