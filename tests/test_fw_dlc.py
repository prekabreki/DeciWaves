from deciwaves.games.fw import dlc


def test_dlc_rows_use_asr_text_and_order_by_group_then_lssr():
    clips = [
        {"line_id": "g5_0001", "group_id": "5", "lssr_index": "1", "wav": "audio/g5_0001.wav"},
        {"line_id": "g5_0000", "group_id": "5", "lssr_index": "0", "wav": "audio/g5_0000.wav"},
        {"line_id": "g2_0000", "group_id": "2", "lssr_index": "0", "wav": "audio/g2_0000.wav"},
    ]
    tx = {"g5_0001": {"transcript": "second", "speech_ratio": "0.9"},
          "g5_0000": {"transcript": "first", "speech_ratio": "0.9"},
          "g2_0000": {"transcript": "earlier group", "speech_ratio": "0.9"}}
    rows = dlc.build_dlc_rows(clips, tx, min_words=0)
    assert [r["line_id"] for r in rows] == ["g2_0000", "g5_0000", "g5_0001"]
    assert [r["gamescript_index"] for r in rows] == [0, 1, 2]
    assert rows[1]["subtitle"] == "first"           # ASR text is the label
    assert rows[1]["speaker"] == ""                  # unattributed
    assert rows[1]["quest"] == "Burning Shores"
    assert rows[1]["tier"] == "D"
    assert rows[1]["wav"] == "audio/g5_0000.wav"


def test_dlc_skips_clips_with_no_transcript():
    clips = [{"line_id": "g1_0000", "group_id": "1", "lssr_index": "0", "wav": "a.wav"},
             {"line_id": "g1_0001", "group_id": "1", "lssr_index": "1", "wav": "b.wav"}]
    tx = {"g1_0000": {"transcript": "has words", "speech_ratio": "0.9"},
          "g1_0001": {"transcript": "   ", "speech_ratio": "0.0"}}   # silent/empty
    rows = dlc.build_dlc_rows(clips, tx, min_words=0)
    assert [r["line_id"] for r in rows] == ["g1_0000"]


def test_min_words_is_required_no_silent_zero_default():
    """build_dlc_rows must require min_words: a silent default of 0 meant a direct
    caller got NO bark filtering (the opposite of this module's purpose)."""
    import pytest
    with pytest.raises(TypeError):
        dlc.build_dlc_rows([], {})        # missing min_words -> explicit failure


def test_is_dlc_clip_by_file_index():
    assert dlc.is_dlc({"file_index": "101"})
    assert not dlc.is_dlc({"file_index": "15"})
    assert not dlc.is_dlc({"file_index": "16"})
