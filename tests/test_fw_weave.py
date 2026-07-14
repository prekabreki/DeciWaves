from games.fw import weave


def _m(line_id, gidx, speaker, subtitle, tier="1"):
    return {"line_id": line_id, "gamescript_index": str(gidx), "speaker": speaker,
            "subtitle": subtitle, "tier": tier, "score": "100", "quest": "Q",
            "transcript": subtitle, "wav": f"audio/{line_id}.wav"}


def _c(line_id, group, lssr, wav=None):
    return {"line_id": line_id, "group_id": str(group), "lssr_index": str(lssr),
            "wav": wav or f"audio/{line_id}.wav", "file_index": "15"}


def test_clean_scene_weaves_unmatched_clips_in_lssr_order():
    # group 5: two anchors (idx 100,102) tight -> clean scene; clip _0001 unmatched, woven
    matched = [_m("g5_0000", 100, "Aloy", "First line here"),
               _m("g5_0002", 102, "Varl", "Third line here")]
    clips = [_c("g5_0000", 5, 0), _c("g5_0001", 5, 1), _c("g5_0002", 5, 2)]
    tx = {"g5_0001": {"transcript": "middle bark interjection", "speech_ratio": "0.9"}}
    rows = weave.build_woven_rows(matched, clips, tx)
    ids = [r["line_id"] for r in rows]
    assert ids == ["g5_0000", "g5_0001", "g5_0002"]      # lssr order within scene
    mid = [r for r in rows if r["line_id"] == "g5_0001"][0]
    assert mid["subtitle"] == "middle bark interjection"  # ASR label
    assert mid["speaker"] == ""                            # unattributed
    assert mid["tier"] == "W"                              # woven


def test_lone_anchor_group_does_not_weave_its_other_clips():
    # group 9: only ONE anchor -> not a confirmed scene -> only the matched clip kept
    matched = [_m("g9_0000", 50, "Aloy", "Only matched line")]
    clips = [_c("g9_0000", 9, 0), _c("g9_0001", 9, 1)]
    tx = {"g9_0001": {"transcript": "some bark", "speech_ratio": "0.9"}}
    rows = weave.build_woven_rows(matched, clips, tx)
    assert [r["line_id"] for r in rows] == ["g9_0000"]     # bark not woven


def test_scattered_anchors_not_treated_as_scene():
    # group 7: two anchors but wildly separated (bark bank w/ stray matches) -> not clean
    matched = [_m("g7_0000", 10, "Aloy", "line a here now"),
               _m("g7_0500", 6000, "Varl", "line b here now")]
    clips = [_c("g7_0000", 7, 0), _c("g7_0001", 7, 1), _c("g7_0500", 7, 500)]
    tx = {"g7_0001": {"transcript": "stray bark", "speech_ratio": "0.9"}}
    rows = weave.build_woven_rows(matched, clips, tx, max_span=120)
    assert "g7_0001" not in [r["line_id"] for r in rows]   # not woven (scattered)


def test_weave_uses_exact_subtitle_for_scene_clips_when_provided():
    # subtitle mode: unmatched scene clips are labeled with their EXACT in-game
    # subtitle (not ASR); a scene clip with no subtitle is dropped.
    matched = [_m("g5_0000", 100, "Aloy", "First line here"),
               _m("g5_0002", 102, "Varl", "Third line here")]
    clips = [_c("g5_0000", 5, 0), _c("g5_0001", 5, 1),
             _c("g5_0002", 5, 2), _c("g5_0003", 5, 3)]
    subs = {"g5_0001": "An exact in-game subtitle."}  # _0003 has none
    rows = weave.build_woven_rows(matched, clips, {}, subtitles_by_id=subs)
    mid = [r for r in rows if r["line_id"] == "g5_0001"][0]
    assert mid["subtitle"] == "An exact in-game subtitle."  # exact, not ASR
    assert mid["tier"] == "W" and mid["speaker"] == ""
    assert "g5_0003" not in [r["line_id"] for r in rows]    # no subtitle -> dropped


def test_output_sorted_by_story_position():
    matched = [_m("g5_0000", 300, "Aloy", "later scene line one"),
               _m("g5_0001", 301, "Varl", "later scene line two"),
               _m("g2_0000", 10, "Aloy", "early lone line here")]
    clips = [_c("g5_0000", 5, 0), _c("g5_0001", 5, 1), _c("g2_0000", 2, 0)]
    rows = weave.build_woven_rows(matched, clips, {})
    # early lone line (story pos 10) before the later scene (~300)
    assert rows[0]["line_id"] == "g2_0000"
    assert [int(r["gamescript_index"]) for r in rows] == [0, 1, 2]  # re-ranked
