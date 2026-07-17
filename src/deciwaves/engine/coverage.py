"""Persisted per-stage coverage summaries (issue #63, GUI spec §5.4).

Coverage and cap-skip numbers used to be computed and then thrown away as
stdout messages -- so a ``--sample-cap``'d rip was indistinguishable ON DISK
from a complete one, and anything wanting the numbers (the GUI coverage bar)
had to scrape stdout. Each stage that computes such numbers now also merges
them, as its own section keyed by stage name, into one per-game JSON artifact
(``out/<game>/coverage.json``).

Sections follow the done-marker contract (issue #81): a stage writes its
section only on success, and whatever deletes a stage's done-marker (cascade
invalidation, ``run --from``) clears its section too -- section absent means
"coverage unknown", exactly like a missing marker means "not done".

The artifact is INFORMATIONAL, and that shapes the error handling: a corrupt
or unreadable existing file is rebuilt with a warning (it's derived data),
and a failed write warns and moves on -- a stage whose real work succeeded is
never failed by its coverage bookkeeping. Concurrent stage runs sharing one
workspace are not supported (the pipeline runs one job at a time, GUI spec
§5.3); two simultaneous writers can lose one section.

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


def _load_object(path: str) -> dict:
    """The artifact's current sections, or ``{}`` (with a warning for anything
    but a simply-missing file). ``ValueError`` covers both ``JSONDecodeError``
    and ``UnicodeDecodeError`` -- a torn write or a tool re-saving the file as
    UTF-16 (this is a Windows-only project) must mean "rebuild the derived
    file", never a crash on every subsequent run (issue #81)."""
    try:
        existing = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        print(f"warning: {path} is corrupted or unreadable ({exc}); rebuilding it")
        return {}
    if not isinstance(existing, dict):
        print(f"warning: {path} held {type(existing).__name__}, not a JSON "
              f"object; rebuilding it")
        return {}
    return existing


def _write_object(path: str, obj: dict) -> None:
    """Atomic replace of the artifact. Never raises on OS-level failure
    (issue #81): a typo'd --coverage-out (an existing directory, a read-only
    location) must not fail a stage whose real work already succeeded --
    coverage is informational, so warn and move on."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        atomic_write(path, lambda tmp: Path(tmp).write_text(
            json.dumps(obj, indent=2) + "\n", encoding="utf-8"))
    except OSError as exc:
        print(f"warning: couldn't write coverage summary {path} ({exc}) -- "
              f"the stage's real outputs are unaffected")


def write_stage_coverage(path: str, stage: str, stats: dict) -> None:
    """Merge ``stats`` into the JSON artifact at ``path`` as section ``stage``,
    creating the file (and parent dirs) if needed.

    Read-modify-write with an atomic replace: stages run as separate,
    sequential processes, each owning one section -- an earlier stage's
    section survives a later stage's write, and a re-run stage replaces its
    own section wholesale (no stale keys from an older schema linger).
    """
    existing = _load_object(path)
    existing[stage] = stats
    _write_object(path, existing)


def clear_stage_coverage(path: str, stage: str) -> None:
    """Drop ``stage``'s section from the artifact at ``path``, leaving sibling
    sections untouched. No-op when the file (or the section) doesn't exist --
    in particular, it never CREATES the file.

    This is the coverage half of marker invalidation (issue #81): whatever
    declares a stage not-done (cli/run.py deleting its marker, or a stage
    about to rewrite its own output) calls this so the artifact stops
    asserting completeness the workspace no longer has.
    """
    if not os.path.isfile(path):
        return
    existing = _load_object(path)
    if stage not in existing:
        return
    del existing[stage]
    _write_object(path, existing)
