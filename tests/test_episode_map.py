# tests/test_episode_map.py
from deciwaves.games.ds import episode_map as em


def test_cs_group_extracts_group():
    assert em.cs_group("sq_cs04_s01650") == "cs04"
    assert em.cs_group("lines_m00010") is None


def test_cs_number_extracts_numeric_ordinal():
    assert em.cs_number("cs07") == 7
    assert em.cs_number("cs00") == 0
    assert em.cs_number("cs71") == 71


def test_cs_number_lexicographic_trap():
    # "cs10" < "cs9" as strings, but 10 > 9 numerically -- the sort key must use the
    # latter or multi-digit groups silently sort before single-digit ones.
    assert em.cs_number("cs10") > em.cs_number("cs9")


def test_cs_number_unparseable_returns_none():
    assert em.cs_number("csXX") is None
    assert em.cs_number("mystery_group") is None


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


def test_non_story_cs_groups_all_have_an_order_hint():
    # Every NON_STORY_CS_GROUPS group must carry a CS_ORDER_HINT entry -- if one is ever
    # removed or typo'd, that group silently falls back to cs_number(group) ordering and
    # can land mid-story instead of at the curated ~980+ tail (see CS_ORDER_HINT comment).
    missing = em.NON_STORY_CS_GROUPS - em.CS_ORDER_HINT.keys()
    assert missing == set()


def test_cs53_order_hint_places_it_between_cs03_and_cs04():
    # Issue #40: cs53 is real main-story (excluded from NON_STORY_CS_GROUPS, see above),
    # but the transcript doesn't reliably anchor it. If this hint is ever removed or
    # typo'd, cs53 silently falls back to raw cs_number(53) and sorts after every other
    # main-story group in the default (no-transcript) order instead of near cs03/cs04.
    assert "cs53" in em.CS_ORDER_HINT
    assert em.cs_number("cs03") < em.CS_ORDER_HINT["cs53"] < em.cs_number("cs04")
