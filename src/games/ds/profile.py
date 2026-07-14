"""DS-specific GameProfile factory.

Usage::

    from games.ds.profile import build_profile
    profile = build_profile(data_dir="path/to/DS:DC/data", oodle="oo2core_7_win64.dll")

`data_dir` and `oodle` may be None when the profile is constructed for prefix/classification
purposes only (e.g. in tests) — pack_reader will be None in that case.
"""
from __future__ import annotations

from engine.profile import GameProfile
from engine import transcript_anchor as ta
from games.ds import episode_map as _em
from games.ds import cutscene_audio as _ca

# Authoritative DS prefix map (Phase 2 Task 2.3).
# engine.catalog aliases this as CORE_PREFIXES for backward compatibility.
DS_CORE_PREFIXES: dict[str, str] = {
    "localized/sentences/ds_lines_cutscene": "cutscene",
    "localized/sentences/ds_lines_mission": "mission",
    "localized/sentences/ds_lines_terminal": "terminal",
    "localized/sentences/ds_lines_npc": "npc",
    "localized/sentences/ds_lines_common": "common",
    "localized/sentences/ds_lines_sam": "sam",
}


def build_profile(data_dir: str | None, oodle: str | None) -> GameProfile:
    """Build and return the DS GameProfile.

    Parameters
    ----------
    data_dir:
        Path to the DS:DC data directory (passed to PackIndex).  May be None
        when the profile is used for prefix/classification purposes only.
    oodle:
        Path to oo2core_7_win64.dll (passed to PackIndex).  May be None
        when pack_reader is not needed.
    """
    if data_dir is not None and oodle is not None:
        from engine.pack.bin_index import PackIndex
        pack_reader = PackIndex(data_dir, oodle)
    else:
        pack_reader = None

    return GameProfile(
        name="ds",
        pack_reader=pack_reader,
        decima_version="DSPC",
        core_prefixes=DS_CORE_PREFIXES,
        speaker_simpletext_filter=lambda p: (
            "sentences/voices/" in p and p.strip().endswith("/simpletext")
        ),
        transcript_path=ta.TRANSCRIPT,
        out_dir="out/ds",
        # episode_map: wired — the module exposes cs_group, fallback_group,
        # scene_number which story_order consumes directly by import; passing
        # the module object here makes it discoverable on the profile.
        episode_map=_em,
        # cutscene_resolver: the cutscene_audio module's resolve_scene function
        # is the natural per-scene resolver callable; store the module so callers
        # can reach both resolve_scene and helper utilities.
        cutscene_resolver=_ca,
    )
