"""Fallback placement + episode titles for Phase D ordering.

Used ONLY where the game transcript does not anchor a scene (see transcript_anchor /
story_order). Cutscene groups are titled here; the fallback tables map an unanchored
mission/terminal/npc scene to a cutscene group. All HAND-AUTHORED first pass; the tables
are the tunable curation surface, refined after a listen.
"""
from __future__ import annotations

import re

CS_TITLES = {
    "cs00": "Prologue - Central Knot City",
    "cs01": "Capital Knot City - Bridget & BB",
    "cs02": "Eastern Region - Wind Farm to Port Knot",
    "cs03": "Ground Zero & Lake Knot City",
    "cs53": "Central Region (cs53)",
    "cs04": "Central Preppers - to South Knot City",
    "cs05": "Mountain Knot & Mama's Lab",
    "cs06": "Heartman's Lab",
    "cs07": "The Mountains - Cliff & beyond",
    "cs08": "Northward to Edge Knot",
    "cs09": "Edge Knot City - Higgs",
    "cs10": "The Last Stranding",
    "cs11": "Finale & Epilogue",
    "cs50": "Extra (cs50)", "cs56": "Extra (cs56)",
    "cs71": "Battlefield (cs71)", "cs77": "Battlefield (cs77)", "cs80": "Battlefield (cs80)",
}

# Order positions (transcript anchor-scale, ~0..1320) for cutscene groups the transcript
# does NOT anchor. Anchored groups use their real anchor instead. cs11 = finale (after cs10).
CS_ORDER_HINT = {
    "cs71": 980.0, "cs77": 1000.0, "cs80": 1020.0,
    "cs11": 1320.0, "cs50": 1340.0, "cs56": 1360.0,
}

# Cutscene groups that are NOT main-story narrative -- DS "Extra" / "Battlefield"
# set-pieces (item-preview announcements like the EX-grenade enumeration, private-room
# BB chatter, repeatable battles). Derived from the titles so it stays in sync. Kept in
# the full/comprehensive reel; excluded from the --main-story spine (render.main_story_only).
NON_STORY_CS_GROUPS = frozenset(
    g for g, title in CS_TITLES.items() if "Extra" in title or "Battlefield" in title
)

_CS_RE = re.compile(r"sq_(cs\d+)_")
_DIGITS_RE = re.compile(r"\d+")

# Unanchored non-cutscene scene -> cutscene group. TUNABLE.
_MISSION_BREAKS = [(30, "cs00"), (85, "cs01"), (150, "cs02"), (200, "cs03"), (270, "cs04"),
                   (360, "cs05"), (450, "cs06"), (510, "cs07"), (560, "cs08"), (620, "cs09"),
                   (660, "cs10"), (10**9, "cs11")]
_TERMINAL_NAME = [("bb_factory", "cs01"), ("windfarm", "cs02"), ("mamaslabo", "cs05"),
                  ("heartmanslabo", "cs06"), ("observatory", "cs06"), ("chiraltower", "cs10"),
                  ("blackholes_base", "cs08")]
_TERMINAL_BREAKS = [(110, "cs02"), (210, "cs03"), (226, "cs04"), (240, "cs05"), (300, "cs04"),
                    (410, "cs08"), (10**9, "cs09")]
_NPC_GROUP = {"amelie": "cs01", "deadman": "cs01", "higgs": "cs02", "mama": "cs05",
              "heartman": "cs06", "artist": "cs06", "cliff": "cs07"}


def cs_group(scene):
    m = _CS_RE.match(scene)
    return m.group(1) if m else None


def scene_number(scene):
    nums = _DIGITS_RE.findall(scene)
    return tuple(int(n) for n in nums) if nums else (0,)


def _last(scene):
    nums = _DIGITS_RE.findall(scene)
    return int(nums[-1]) if nums else 0


def fallback_group(category, scene):
    if category == "mission":
        n = _last(scene)
        for upper, g in _MISSION_BREAKS:
            if n <= upper:
                return g
    if category == "terminal":
        for needle, g in _TERMINAL_NAME:
            if needle in scene:
                return g
        n = _last(scene)
        for upper, g in _TERMINAL_BREAKS:
            if n <= upper:
                return g
    if category == "npc":
        for name, g in _NPC_GROUP.items():
            if name in scene:
                return g
    return "cs00"


def radio_episode(rank, total, n_episodes):
    if total <= 1 or n_episodes <= 1:
        return 0
    return min((rank * n_episodes) // total, n_episodes - 1)
