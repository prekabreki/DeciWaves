from deciwaves.games.fw import bulk


def _clip(line_id, group_id, lssr, wav=None):
    return {"line_id": line_id, "group_id": str(group_id), "lssr_index": str(lssr),
            "wav": wav or f"audio/{line_id}.wav"}


def test_bulk_rows_order_by_group_then_lssr_with_running_index():
    clips = [_clip("g5_0001", 5, 1), _clip("g5_0000", 5, 0), _clip("g2_0000", 2, 0)]
    tx = {c: {"transcript": f"line {c}", "speech_ratio": "0.9"}
          for c in ("g5_0001", "g5_0000", "g2_0000")}
    rows = bulk.build_bulk_rows(clips, tx)
    assert [r["line_id"] for r in rows] == ["g2_0000", "g5_0000", "g5_0001"]
    assert [r["gamescript_index"] for r in rows] == [0, 1, 2]


def test_bulk_quest_is_group_for_packing_and_tier_b():
    clips = [_clip("g7_0000", 7, 0)]
    tx = {"g7_0000": {"transcript": "hello there", "speech_ratio": "0.9"}}
    [r] = bulk.build_bulk_rows(clips, tx)
    assert r["quest"] == "g7"            # group is the packing/episode unit
    assert r["tier"] == "B"
    assert r["subtitle"] == "hello there"
    assert r["speaker"] == ""


def test_bulk_excludes_given_ids_and_empty():
    clips = [_clip("a", 1, 0), _clip("b", 1, 1), _clip("c", 1, 2)]
    tx = {"a": {"transcript": "keep me", "speech_ratio": "0.9"},
          "b": {"transcript": "in story reel", "speech_ratio": "0.9"},
          "c": {"transcript": "  ", "speech_ratio": "0.0"}}
    rows = bulk.build_bulk_rows(clips, tx, exclude={"b"})
    assert [r["line_id"] for r in rows] == ["a"]    # b excluded, c empty
