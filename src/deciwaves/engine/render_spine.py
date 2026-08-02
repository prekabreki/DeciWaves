"""Game-agnostic render spine: gamescript-bound manifest -> ordered, episode-packed playlist.

Turns any manifest whose rows carry ``line_id`` / ``gamescript_index`` /
``quest`` / ``tier`` / ``speaker`` / ``subtitle`` / ``wav`` into the ordered
list of bound lines the render stage packs into reels. Rows are filtered to the
bound tiers, sorted by ``gamescript_index`` (rough chronological; the gamescript
already interleaves main/side/DLC), and each distinct ``quest`` becomes a dense
``episode`` index (the packing unit) in gamescript order.

This module is imported by per-game render modules (``games/fw/render.py``
re-exports it behind a shim; DS2's render stage will do the same) which keep
only their own ``main()`` CLI, audio handling, and default paths. Kept separate
from ``engine/render.py``, which is the *assembly* kit (measure -> budget ->
pack -> concat) that consumes a built spine.
"""

from __future__ import annotations

from dataclasses import dataclass

# The default tier list a gamescript-bound manifest ships with. ``BOUND_TIERS``
# is its parsed set; ``games/fw/render.py`` keeps its own ``DEFAULT_TIERS`` as
# the CLI's ``--tiers`` default and must stay in lockstep with this string.
DEFAULT_TIERS = "1,2,S"
BOUND_TIERS = {t.strip() for t in DEFAULT_TIERS.split(",") if t.strip()}


@dataclass
class RenderItem:
    gamescript_index: int
    episode: int            # dense rank of the quest (the packing unit)
    quest: str
    speaker: str
    subtitle: str
    line_id: str
    wav: str                # path relative to the audio root


def build_spine(manifest_rows, bound_tiers=BOUND_TIERS) -> list[RenderItem]:
    """Ordered playlist of bound lines, sorted by gamescript index.

    Each distinct quest becomes a dense episode index (the packing unit), assigned
    in gamescript order. Lines whose tier is not in ``bound_tiers`` are dropped.
    """
    rows = [r for r in manifest_rows if r["tier"].strip() in bound_tiers]
    rows.sort(key=lambda r: int(r["gamescript_index"]))
    ep_of: dict[str, int] = {}
    spine = []
    for r in rows:
        ep_of.setdefault(r["quest"], len(ep_of))
        spine.append(RenderItem(
            gamescript_index=int(r["gamescript_index"]),
            episode=ep_of[r["quest"]], quest=r["quest"],
            speaker=r["speaker"], subtitle=r["subtitle"],
            line_id=r["line_id"], wav=r["wav"]))
    return spine


# Columns build_spine reads. A manifest missing any of them -- a garbled
# header, or the wrong CSV entirely -- would otherwise crash build_spine with a
# raw `KeyError`; validate up front for a clean, actionable error (issue #84,
# mirroring the #7/#23 message convention).
REQUIRED_COLS = ("line_id", "gamescript_index", "quest", "tier",
                 "speaker", "subtitle", "wav")
