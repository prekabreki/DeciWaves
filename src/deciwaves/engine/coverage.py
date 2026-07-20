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


def read_json_object(path: str) -> dict:
    """Shared corrupt-tolerant JSON-object read.

    Returns the parsed dict, or ``{}`` (with a warning) for a missing file,
    corrupt/UTF-16 bytes, or a JSON value that is not an object (issue #81).
    Never raises -- a corrupt derived file must not crash the running stage.

    Single home of this contract (issue #91): both ``coverage``'s own load and
    ``cli.config.load()`` use this, so there is exactly one implementation of
    the corrupt-tolerant read to get right."""
    try:
        existing = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        print(f"warning: {path} is corrupted or unreadable ({exc}); ignoring it")
        return {}
    if not isinstance(existing, dict):
        print(f"warning: {path} held {type(existing).__name__}, not a JSON "
              f"object; ignoring it")
        return {}
    return existing


def _load_object(path: str) -> dict:
    """Thin wrapper around ``read_json_object`` for callers that still want
    the ``_``-prefixed name (internal coverage users)."""
    return read_json_object(path)


def _write_object(path: str, obj: dict) -> None:
    """Atomic replace of the artifact. Never raises (issue #81): a stage whose
    real work already succeeded must not be failed by its coverage bookkeeping.

    Two failure classes are swallowed at this informational boundary:
    ``OSError`` for an unwritable target (a typo'd --coverage-out pointing at an
    existing directory or a read-only location), and ``TypeError``/``ValueError``
    from ``json.dumps`` for a non-serializable stat (a set, ``Path``, datetime,
    numpy scalar, or a circular ref -- issue #87 finding 3). No current caller
    passes such a value, so the latter guards the contract, not a live crash."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        atomic_write(path, lambda tmp: Path(tmp).write_text(
            json.dumps(obj, indent=2) + "\n", encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
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

    The leading ``os.path.isfile`` guard was removed in issue #91 (item 9):
    ``_load_object`` (via ``read_json_object``) already returns ``{}`` for a
    missing file, and the ``stage not in existing`` check below is the genuine
    early-exit."""
    existing = _load_object(path)
    if stage not in existing:
        return
    del existing[stage]
    _write_object(path, existing)


def clear_sections(path: str, stages: list[str]) -> None:
    """Drop *multiple* sections from the artifact at ``path`` in a single
    read-modify-write. No-op when the file (or all named sections) don't
    exist.

    Added in issue #91 (item 10) so cascade invalidation
    (``cli.run._invalidate_downstream_markers``) does one coverage.json
    read-modify-write instead of one per downstream stage."""
    existing = _load_object(path)
    remaining = {k: v for k, v in existing.items() if k not in stages}
    if len(remaining) < len(existing):
        _write_object(path, remaining)
