from deciwaves.engine.gamescript import parse


def test_parses_speaker_and_text():
    [line] = parse("Aloy: What now?")
    assert line.speaker == "Aloy"
    assert line.text == "What now?"


def test_skips_stage_direction():
    lines = parse("[The ground shakes.]\nAloy: Here we go.")
    assert len(lines) == 1
    assert lines[0].speaker == "Aloy"


def test_captures_allcaps_header_as_quest():
    lines = parse("THE EMBASSY\nAloy: Hello.")
    assert lines[0].quest == "THE EMBASSY"


def test_strips_parenthetical_from_text():
    [line] = parse("Aloy: (softly) Goodbye.")
    assert line.text == "Goodbye."
