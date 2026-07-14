from deciwaves.games.fw import assemble


def test_combines_in_order_with_continuous_index():
    story = [{"line_id": "s1", "gamescript_index": "0", "quest": "Q1"},
             {"line_id": "s2", "gamescript_index": "1", "quest": "Q1"}]
    dlc = [{"line_id": "d1", "gamescript_index": "0", "quest": "Epilogue"}]
    rows = assemble.combine([story, dlc])
    assert [r["line_id"] for r in rows] == ["s1", "s2", "d1"]      # story then dlc
    assert [r["gamescript_index"] for r in rows] == [0, 1, 2]      # continuous re-rank


def test_preserves_other_fields():
    a = [{"line_id": "x", "gamescript_index": "5", "quest": "Q", "speaker": "Aloy"}]
    b = [{"line_id": "y", "gamescript_index": "9", "quest": "Epilogue", "speaker": ""}]
    rows = assemble.combine([a, b])
    assert rows[0]["speaker"] == "Aloy" and rows[0]["quest"] == "Q"
    assert rows[1]["line_id"] == "y" and rows[1]["gamescript_index"] == 1
