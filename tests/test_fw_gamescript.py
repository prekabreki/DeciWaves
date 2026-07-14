import hashlib
from pathlib import Path

import pytest

from deciwaves.games.fw.gamescript import ScriptLine, parse, parse_file

REPO = Path(__file__).resolve().parents[1]
GAMESCRIPT = REPO / "docs" / "forbidden_west_gamescript.md"

# sha256 of the expected opening-line prefix — oracle value without shipping the text
EXPECT_PREFIX_LEN = 52
EXPECT_PREFIX_SHA = "6312fed90dd1adaff24f90a3b726917c2163964916348817d83a0b8cd56df26b"


def test_parses_speaker_and_text():
    [line] = parse("Aloy: I'm running out of time.")
    assert line.speaker == "Aloy"
    assert line.text == "I'm running out of time."


def test_assigns_sequential_index():
    lines = parse("Aloy: One.\nVarl: Two.\nAloy: Three.")
    assert [l.index for l in lines] == [0, 1, 2]
    assert [l.speaker for l in lines] == ["Aloy", "Varl", "Aloy"]


def test_skips_bracket_stage_directions():
    lines = parse("[A fox runs through the woods.]\nAloy: Hello.")
    assert len(lines) == 1
    assert lines[0].text == "Hello."


def test_skips_blank_and_non_dialogue_prose():
    # Preamble metadata / blank lines carry no "Speaker: " and are not dialogue.
    lines = parse("Game Scripts Wiki Blog\n\nPlatforms\tPlayStation 5\n\nAloy: Hi.")
    assert len(lines) == 1
    assert lines[0].speaker == "Aloy"


def test_strips_leading_parenthetical_stage_direction():
    [line] = parse("Aloy: (offscreen) Get to the grass!")
    assert line.speaker == "Aloy"
    assert line.text == "Get to the grass!"


def test_strips_inline_parentheticals():
    [line] = parse("Aloy: Some blight. (sighs) But for now we go.")
    assert line.text == "Some blight. But for now we go."


def test_dual_speaker_label_kept():
    [line] = parse("Aloy & Morlund: We agree.")
    assert line.speaker == "Aloy & Morlund"
    assert line.text == "We agree."


def test_tracks_quest_header():
    src = "REACH FOR THE STARS\nAloy: First.\nTHE EMBASSY\nVarl: Second."
    lines = parse(src)
    assert lines[0].quest == "REACH FOR THE STARS"
    assert lines[1].quest == "THE EMBASSY"


def test_quest_empty_before_any_header():
    [line] = parse("Aloy: No header yet.")
    assert line.quest == ""


def test_captures_titlecase_sidequest_header_after_content():
    src = ("REACH FOR THE STARS\nAloy: Main line.\n"
           "Deep Trouble (start)\nErend: Side line.\n"
           "Breaking Even\nPetra: Another side line.")
    lines = parse(src)
    assert lines[0].quest == "REACH FOR THE STARS"
    assert lines[1].quest == "Deep Trouble"          # (start) marker stripped
    assert lines[2].quest == "Breaking Even"


def test_preamble_titlecase_is_not_a_quest():
    # Title-case blog/metadata cruft before any dialogue must not become a quest.
    src = "Game Scripts Wiki Blog\nSearch this blog\nAloy: First real line."
    [line] = parse(src)
    assert line.quest == ""


@pytest.mark.skipif(not GAMESCRIPT.exists(), reason="gamescript not present")
def test_real_file_anchors():
    lines = parse_file(GAMESCRIPT)
    # Prologue opens with Sylens' voice-over.
    assert lines[0].speaker == "Sylens"
    prefix = lines[0].text[:EXPECT_PREFIX_LEN]
    assert hashlib.sha256(prefix.encode("utf-8")).hexdigest() == EXPECT_PREFIX_SHA
    # Aloy is the dominant speaker; sanity on volume + indexing.
    assert sum(1 for l in lines if l.speaker == "Aloy") > 2500
    assert len(lines) > 6000
    assert [l.index for l in lines] == list(range(len(lines)))
