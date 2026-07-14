from games.fw import bind
from games.fw.gamescript import ScriptLine
from games.fw.match_lines import LineBind


def _script():
    return [ScriptLine(0, "Aloy", "I'll find a way", "REACH FOR THE STARS"),
            ScriptLine(1, "Varl", "We head north", "THE EMBASSY")]


def test_manifest_row_joins_wav_and_quest():
    binds = [LineBind("c0", 0, "Aloy", "I'll find a way", 95.0, "1", "ill find a way")]
    clip_index = {"c0": {"wav": "audio/c0.wav"}}
    rows = bind.build_manifest_rows(binds, clip_index, _script())
    assert len(rows) == 1
    r = rows[0]
    assert r["line_id"] == "c0"
    assert r["wav"] == "audio/c0.wav"
    assert r["speaker"] == "Aloy"
    assert r["subtitle"] == "I'll find a way"
    assert r["gamescript_index"] == 0
    assert r["quest"] == "REACH FOR THE STARS"
    assert r["tier"] == "1"
    assert r["score"] == 95.0
    assert r["transcript"] == "ill find a way"


def test_manifest_excludes_unbound_clips():
    binds = [LineBind("c0", 0, "Aloy", "I'll find a way", 95.0, "1", "x"),
             LineBind("c1", None, "", "", 40.0, "3", "gibberish")]
    rows = bind.build_manifest_rows(binds, {"c0": {"wav": "a.wav"}}, _script())
    assert [r["line_id"] for r in rows] == ["c0"]


def test_manifest_cols_order_stable():
    assert bind.MANIFEST_COLS[:5] == [
        "line_id", "wav", "speaker", "subtitle", "gamescript_index"]
