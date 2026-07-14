"""Tests for the full 16.7h subtitled-reel assembler (#37).

Ships EVERY exact-subtitled line, ordered by the best signal available: anchored
groups (those containing matched story lines) sit at their gamescript story
position; unanchored base groups follow as scene-clustered blocks; DLC last as
the post-game epilogue. Matched lines keep their speaker.
"""
from games.fw.story_full import build_full_reel
from games.fw.bind import MANIFEST_COLS


def _s(line_id, subtitle):
    return {"line_id": line_id, "wav": f"audio/{line_id}.wav", "speaker": "",
            "subtitle": subtitle, "gamescript_index": "", "quest": "",
            "tier": "S", "score": "100", "transcript": subtitle}


def _a(line_id, gidx, speaker, quest, tier="1"):
    return {"line_id": line_id, "wav": f"audio/{line_id}.wav", "speaker": speaker,
            "subtitle": "x", "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "score": "100", "transcript": "x"}


def test_orders_anchored_groups_then_unanchored_then_dlc():
    subs = [_s("g50_0000", "late story line"),      # anchored group 50 @ gidx 500
            _s("g10_0000", "early story line"),      # anchored group 10 @ gidx 20
            _s("g99_0000", "unanchored scene line"), # no anchor
            _s("g200_0000", "dlc line")]             # DLC
    anchors = [_a("g50_0000", 500, "Aloy", "Late Quest"),
               _a("g10_0000", 20, "Varl", "Early Quest")]
    rows = build_full_reel(subs, anchors, dlc_line_ids={"g200_0000"})
    assert [r["line_id"] for r in rows] == [
        "g10_0000", "g50_0000", "g99_0000", "g200_0000"]
    assert [r["gamescript_index"] for r in rows] == [0, 1, 2, 3]  # continuous


def test_matched_lines_keep_speaker_quest_tier():
    subs = [_s("g10_0000", "the line as subtitled")]
    anchors = [_a("g10_0000", 20, "Varl", "Early Quest", tier="1")]
    rows = build_full_reel(subs, anchors, dlc_line_ids=set())
    assert rows[0]["speaker"] == "Varl"
    assert rows[0]["quest"] == "Early Quest"
    assert rows[0]["tier"] == "1"
    # label stays the exact in-game subtitle, not the anchor's placeholder
    assert rows[0]["subtitle"] == "the line as subtitled"


def test_unanchored_lines_have_no_speaker_and_subtitle_tier():
    subs = [_s("g99_0000", "scene line")]
    rows = build_full_reel(subs, [], dlc_line_ids=set())
    assert rows[0]["speaker"] == ""
    assert rows[0]["tier"] == "S"
    assert rows[0]["quest"].startswith("(unsorted scenes")


def test_unsorted_block_chunked_into_sized_episodes():
    # the unsorted block must split into bounded episodes so no single episode
    # overflows the render's <=290MB-per-file packing unit.
    subs = [_s(f"g{900 + i}_0000", f"line {i}") for i in range(5)]
    rows = build_full_reel(subs, [], dlc_line_ids=set(), unsorted_chunk=2)
    quests = [r["quest"] for r in rows]
    assert quests == ["(unsorted scenes 1)", "(unsorted scenes 1)",
                      "(unsorted scenes 2)", "(unsorted scenes 2)",
                      "(unsorted scenes 3)"]


def test_scene_mates_of_anchored_group_travel_with_it_in_lssr_order():
    # group 10 anchored at gidx 20; its other clips (no anchor) ride along, in
    # lssr order, at the group's story position — keeping the scene intact.
    subs = [_s("g10_0002", "third"), _s("g10_0000", "first"),
            _s("g10_0001", "second"), _s("g50_0000", "later")]
    anchors = [_a("g10_0000", 20, "Aloy", "Q"), _a("g50_0000", 500, "Aloy", "Q2")]
    rows = build_full_reel(subs, anchors, dlc_line_ids=set())
    assert [r["line_id"] for r in rows][:3] == [
        "g10_0000", "g10_0001", "g10_0002"]  # lssr order within the scene


def test_scene_mate_inherits_its_anchored_groups_quest():
    # the unmatched clip in an anchored group should carry that scene's quest,
    # not "(unsorted scenes)" — so the whole scene packs as one episode.
    subs = [_s("g10_0000", "matched"), _s("g10_0001", "scene mate")]
    anchors = [_a("g10_0000", 20, "Aloy", "The Embassy")]
    rows = build_full_reel(subs, anchors, dlc_line_ids=set())
    mate = next(r for r in rows if r["line_id"] == "g10_0001")
    assert mate["quest"] == "The Embassy"
    assert mate["speaker"] == "" and mate["tier"] == "S"


def test_dlc_block_ordered_by_group_then_lssr_and_labeled_epilogue():
    subs = [_s("g201_0001", "b"), _s("g200_0000", "a"), _s("g201_0000", "c")]
    rows = build_full_reel(subs, [], dlc_line_ids={"g200_0000", "g201_0000", "g201_0001"})
    assert [r["line_id"] for r in rows] == ["g200_0000", "g201_0000", "g201_0001"]
    assert all(r["quest"] == "Burning Shores (Epilogue)" for r in rows)


def test_output_uses_manifest_schema():
    subs = [_s("g10_0000", "x")]
    rows = build_full_reel(subs, [_a("g10_0000", 1, "Aloy", "Q")], dlc_line_ids=set())
    assert list(rows[0].keys()) == MANIFEST_COLS
