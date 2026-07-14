from deciwaves.games.hzd.render import mq_rank, build_spine


def test_mq_rank_parses_variants():
    assert mq_rank("mq04_mothersheart") == 4.0
    assert mq_rank("mq01_papooserider") == 1.0
    assert mq_rank("mq01_5_giftfromthepast") == 1.5
    assert mq_rank("mq15.5_rallytheforces") == 15.5
    assert mq_rank("mq16_thefaceofextinction") == 16.0
    assert mq_rank("dlc1_tba03") is None
    assert mq_rank("banditcamps/bc_ic_jom") is None


def test_build_spine_orders_filters_and_assigns_episodes():
    catalog = {
        "MQ04_a": {"category": "mission", "subtitle_en": "Four A", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "1"},
        "MQ04_b": {"category": "mission", "subtitle_en": "Four B", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "0"},
        "MQ06_a": {"category": "mission", "subtitle_en": "Six", "speaker_name": "erend",
                   "scene": "mq06_aftermath", "line_index": "0"},
        "AMB":    {"category": "ambient", "subtitle_en": "bark", "speaker_name": "x",
                   "scene": "mq04_mothersheart", "line_index": "5"},
        "SIDE":   {"category": "mission", "subtitle_en": "side", "speaker_name": "y",
                   "scene": "tcb01_foo", "line_index": "0"},
    }
    manifest = [
        {"clip_row": "10", "line_id": "MQ04_a", "tier": "S"},
        {"clip_row": "11", "line_id": "MQ04_b", "tier": "1"},
        {"clip_row": "12", "line_id": "MQ06_a", "tier": "S"},
        {"clip_row": "13", "line_id": "AMB",    "tier": "S"},   # ambient -> excluded
        {"clip_row": "14", "line_id": "SIDE",   "tier": "S"},   # side quest -> excluded
        {"clip_row": "15", "line_id": "MQ04_a", "tier": "3"},   # unbound dup -> excluded
    ]
    clip_index = {10: {"offset": "100", "a_bytes": "50"},
                  11: {"offset": "200", "a_bytes": "60"},
                  12: {"offset": "300", "a_bytes": "70"}}
    spine = build_spine(manifest, catalog, clip_index)

    # only the 3 main-quest bound story lines, mq04 (line_index 0 then 1) then mq06
    assert [s.line_id for s in spine] == ["MQ04_b", "MQ04_a", "MQ06_a"]
    # whole quests become episodes for packing: mq04 -> 0, mq06 -> 1
    assert [s.episode for s in spine] == [0, 0, 1]
    # decode coords carried through from clip_index
    assert spine[0].offset == 200 and spine[0].a_bytes == 60
    assert spine[0].speaker == "aloy" and spine[0].subtitle == "Four B"


def test_build_spine_interleaves_side_quests_by_episode_map():
    """With an episode_map, side/DLC questlines interleave at their unlock rank;
    main quests keep their mq# rank. Nothing is dropped (keep side quests + tidbits)."""
    catalog = {
        "MQ04_a": {"category": "mission", "subtitle_en": "Four", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "0"},
        "MQ06_a": {"category": "mission", "subtitle_en": "Six", "speaker_name": "erend",
                   "scene": "mq06_aftermath", "line_index": "0"},
        "SIDE_a": {"category": "other", "subtitle_en": "Side", "speaker_name": "nil",
                   "scene": "tnb01_theonethatgotaway/conv", "line_index": "0"},
        "DLC_a":  {"category": "dlc", "subtitle_en": "Cut", "speaker_name": "aratak",
                   "scene": "dlc1_tba03/base", "line_index": "0"},
        "UNK_a":  {"category": "other", "subtitle_en": "Mystery", "speaker_name": "x",
                   "scene": "zzz_unmapped/conv", "line_index": "0"},
    }
    manifest = [{"clip_row": str(i), "line_id": lid, "tier": "S"}
                for i, lid in enumerate(["MQ04_a", "MQ06_a", "SIDE_a", "DLC_a", "UNK_a"])]
    clip_index = {i: {"offset": str(i * 10), "a_bytes": "50"} for i in range(5)}
    em = {"tnb01_theonethatgotaway": 4.5, "dlc1_tba03": 12.5}

    spine = build_spine(manifest, catalog, clip_index, episode_map=em)
    # mq04(4.0) -> side tnb01(4.5) -> mq06(6.0) -> dlc(12.5) -> unmapped(end, not dropped)
    assert [s.line_id for s in spine] == ["MQ04_a", "SIDE_a", "MQ06_a", "DLC_a", "UNK_a"]


def test_scenes_within_quest_ordered_by_line_sequence_not_alphabetical():
    """Within a quest, scenes must order by their embedded line sequence, not alphabet.
    Prologue: 'thewalk' (Dial_020..) precedes 'namingceremony' (Dial_220..) even though
    'namingceremony' < 'thewalk' alphabetically."""
    catalog = {
        "MQ010_cut_Prologue_Dial_020": {"category": "mission", "subtitle_en": "walk a",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_thewalk", "line_index": "0"},
        "MQ010_cut_Prologue_Dial_040": {"category": "mission", "subtitle_en": "walk b",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_thewalk", "line_index": "1"},
        "MQ010_cut_Prologue_Dial_220": {"category": "mission", "subtitle_en": "ceremony a",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_namingceremony", "line_index": "0"},
    }
    manifest = [{"clip_row": str(i), "line_id": lid, "tier": "S"}
                for i, lid in enumerate(catalog)]
    clip_index = {i: {"offset": str(i), "a_bytes": "1"} for i in range(len(catalog))}
    spine = build_spine(manifest, catalog, clip_index)
    assert [s.scene.split("/")[-1] for s in spine] == [
        "mq010_cut_thewalk", "mq010_cut_thewalk", "mq010_cut_namingceremony"]


def test_build_spine_skips_lines_without_clip_coords():
    catalog = {"MQ04_a": {"category": "mission", "subtitle_en": "A", "speaker_name": "aloy",
                          "scene": "mq04_mothersheart", "line_index": "0"}}
    manifest = [{"clip_row": "99", "line_id": "MQ04_a", "tier": "S"}]
    spine = build_spine(manifest, catalog, {})   # clip_row 99 absent
    assert spine == []
