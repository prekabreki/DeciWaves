"""Tests for the exact-subtitle -> gamescript matcher (story-reel stage).

Matches each gamescript line to the clip whose EXACT in-game subtitle voices it.
The label is the exact subtitle; speaker / quest / chronological order come from
the script. Barks (no script home) drop out; variant clips collapse to one per
script line.
"""
from collections import namedtuple

from deciwaves.games.fw.subtitle_match import match_subtitles, build_rows
from deciwaves.games.fw.bind import MANIFEST_COLS

SL = namedtuple("SL", "index speaker text quest")


def _rows(*pairs):
    """pairs of (line_id, subtitle) -> manifest-row dicts."""
    return [{"line_id": lid, "wav": f"audio/{lid}.wav", "subtitle": sub,
             "transcript": sub} for lid, sub in pairs]


def test_exact_subtitle_binds_to_script_line_with_speaker_and_order():
    script = [
        SL(0, "Aloy", "This ridge has more wreckage than the maps show.", "The Bristlebacks"),
        SL(1, "Sylens", "Word of your deeds is spreading through the camps.", "The Bristlebacks"),
    ]
    rows = _rows(("g5_0001", "Word of your deeds is spreading through the camps."),
                 ("g5_0000", "This ridge has more wreckage than the maps show."))
    binds = match_subtitles(rows, script, accept=80)
    # bound in chronological (gamescript) order
    assert [b.gamescript_index for b in binds] == [0, 1]
    assert [b.line_id for b in binds] == ["g5_0000", "g5_0001"]
    assert binds[0].speaker == "Aloy"
    assert binds[1].speaker == "Sylens"
    assert binds[0].quest == "The Bristlebacks"
    assert binds[0].tier == "1"


def test_label_is_exact_ingame_subtitle_not_script_text():
    # script text and on-screen subtitle differ slightly (fan transcript vs game)
    script = [SL(0, "Aloy", "Okay, I should search the old ruins.", "Q")]
    rows = _rows(("g1_0000", "Okay. I should search the old ruins, watch for traps."))
    binds = match_subtitles(rows, script, accept=70)
    assert len(binds) == 1
    # the exact in-game subtitle is the label, not the script's wording
    assert binds[0].subtitle == "Okay. I should search the old ruins, watch for traps."


def test_bark_with_no_script_home_is_dropped():
    script = [SL(0, "Aloy", "This ridge has more wreckage than the maps show.", "Q")]
    rows = _rows(("g9_0000", "This ridge has more wreckage than the maps show."),
                 ("g9_0001", "Better check the old signal tower for supplies."))  # bark
    binds = match_subtitles(rows, script, accept=80)
    assert [b.line_id for b in binds] == ["g9_0000"]


def test_multi_sentence_script_line_binds_each_sentence_in_order():
    # a script "line" is a speaker's whole turn (often several sentences), but
    # the game shows one subtitle card per sentence -> each card should bind.
    script = [SL(0, "Sylens",
                 "Word of your deeds is spreading through the camps. "
                 "The Carja have taken notice.", "Q")]
    rows = _rows(("g1_0000", "Word of your deeds is spreading through the camps."),
                 ("g1_0001", "The Carja have taken notice."))
    binds = match_subtitles(rows, script, accept=80)
    assert len(binds) == 2
    assert [b.subtitle for b in binds] == [
        "Word of your deeds is spreading through the camps.", "The Carja have taken notice."]
    assert all(b.gamescript_index == 0 for b in binds)   # same script turn
    assert all(b.speaker == "Sylens" for b in binds)


def test_variant_clips_collapse_to_one_per_script_line():
    # same beat re-recorded as 3 variants; only one clip should bind the line
    script = [SL(0, "Aloy", "That old recorder must be from the earlier survey team.", "Q")]
    rows = _rows(
        ("g2_0000", "That old recorder must be from the earlier survey team."),
        ("g2_0001", "That old recorder must be from the earlier survey team group."),
        ("g2_0002", "That old recorder must be from the earlier team. The survey made it."),
    )
    binds = match_subtitles(rows, script, accept=80)
    assert len(binds) == 1
    assert binds[0].gamescript_index == 0


def test_each_clip_used_once_across_repeated_script_lines():
    # script repeats a line; greedy keeps each clip serving exactly one line
    script = [
        SL(0, "Aloy", "Time to switch on my Focus and look around.", "Q"),
        SL(5, "Aloy", "Time to switch on my Focus and look around.", "Q"),
    ]
    rows = _rows(("g3_0000", "Time to switch on my Focus and look around."))
    binds = match_subtitles(rows, script, accept=80)
    # only one clip exists -> only one of the two repeats can bind
    assert len(binds) == 1


def test_build_rows_emits_manifest_schema_in_order():
    script = [
        SL(0, "Aloy", "This ridge has more wreckage than the maps show.", "The Bristlebacks"),
        SL(3, "Varl", "Let's fall back and regroup near the old wall.", "The Bristlebacks"),
    ]
    rows = _rows(("g5_0000", "This ridge has more wreckage than the maps show."),
                 ("g5_0001", "Let's fall back and regroup near the old wall."))
    binds = match_subtitles(rows, script, accept=80)
    out = build_rows(binds)
    assert all(list(r.keys()) == MANIFEST_COLS for r in out)
    assert [r["gamescript_index"] for r in out] == [0, 3]
    assert out[0]["speaker"] == "Aloy"
    assert out[0]["subtitle"] == "This ridge has more wreckage than the maps show."
    assert out[0]["tier"] == "1"
    assert out[0]["wav"] == "audio/g5_0000.wav"
