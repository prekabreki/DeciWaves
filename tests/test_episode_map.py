# tests/test_episode_map.py
from games.ds import episode_map as em


def test_cs_group_extracts_group():
    assert em.cs_group("sq_cs04_s01650") == "cs04"
    assert em.cs_group("lines_m00010") is None


def test_non_story_cs_groups_are_the_extra_and_battlefield_titles():
    # The main-story cull excludes exactly the Extra/Battlefield cutscene groups,
    # and never a real story episode.
    assert em.NON_STORY_CS_GROUPS == {"cs50", "cs56", "cs71", "cs77", "cs80"}
    for g in em.NON_STORY_CS_GROUPS:
        assert ("Extra" in em.CS_TITLES[g]) or ("Battlefield" in em.CS_TITLES[g])
    for story in ("cs00", "cs01", "cs10", "cs11", "cs53"):
        assert story not in em.NON_STORY_CS_GROUPS


def test_scene_number():
    assert em.scene_number("sq_cs02_s00400") == (2, 400)
    assert em.scene_number("lines_pr201") == (201,)


def test_fallback_group_mission_increases():
    assert em.fallback_group("mission", "lines_m00010") == "cs00"
    assert em.fallback_group("mission", "lines_m00700") == "cs11"


def test_fallback_group_terminal_name_beats_number():
    assert em.fallback_group("terminal", "lines_mamaslabo_233") == "cs05"
    assert em.fallback_group("terminal", "lines_heartmanslabo_239") == "cs06"


def test_fallback_group_npc_character():
    assert em.fallback_group("npc", "lines_amelie") == "cs01"
    assert em.fallback_group("npc", "lines_cliff") == "cs07"


def test_radio_proportional_split():
    assert em.radio_episode(0, 120, 12) == 0
    assert em.radio_episode(119, 120, 12) == 11
    assert em.radio_episode(60, 120, 12) == 6


def test_every_cutscene_group_has_a_title():
    for g in ("cs00", "cs10", "cs11", "cs53", "cs71"):
        assert g in em.CS_TITLES
