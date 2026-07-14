from deciwaves.games.fw import match_lines
from deciwaves.games.fw.gamescript import ScriptLine


def _script(*pairs):
    return [ScriptLine(i, sp, txt, "QUEST") for i, (sp, txt) in enumerate(pairs)]


def _tx(line_id, text, speech_ratio=0.9):
    return {"line_id": line_id, "transcript": text, "speech_ratio": speech_ratio}


def test_binds_script_line_to_its_clip():
    script = _script(("Aloy", "Those ruins. That is where we need to go."),
                     ("Varl", "Look there. More of the blight nearby."))
    tx = [_tx("c0", "Those ruins, that is where we need to go."),
          _tx("c1", "Look, there. More of the blight nearby.")]
    binds = {b.script_index: b for b in match_lines.match_all(tx, script)}
    assert binds[0].line_id == "c0"
    assert binds[0].speaker == "Aloy"
    assert binds[0].subtitle == "Those ruins. That is where we need to go."
    assert binds[0].tier == "1"
    assert binds[1].line_id == "c1"


def test_binds_returned_in_script_order():
    script = _script(("Aloy", "I will find a way to stop the blight today"),
                     ("Varl", "We should head north to the ruins now"))
    tx = [_tx("c1", "We should head north to the ruins now"),
          _tx("c0", "I will find a way to stop the blight today")]
    binds = match_lines.match_all(tx, script)
    assert [b.script_index for b in binds] == [0, 1]


def test_unrelated_clip_not_bound():
    script = _script(("Aloy", "I will find a way to stop the blight today"))
    binds = match_lines.match_all([_tx("c0", "totally unrelated nonsense phrase about nothing")], script)
    assert binds == []


def test_short_subset_clip_does_not_claim_long_line():
    # token_sort penalizes length mismatch, so a fragment can't grab a long line.
    script = _script(("Aloy", "Got it. Its eye is a weak spot right there look"))
    binds = match_lines.match_all([_tx("c0", "it is a weak spot")], script)
    assert all(b.tier != "1" for b in binds)        # never confident
    assert not any(b.score >= 90 for b in binds)


def test_each_clip_serves_one_line():
    script = _script(("Aloy", "Open the gate right now we must hurry"),
                     ("Varl", "Open the gate right now we must hurry"))
    binds = match_lines.match_all([_tx("c0", "Open the gate right now we must hurry")], script)
    assert len(binds) == 1                            # one clip -> one bound line


def test_short_script_line_dropped():
    script = _script(("Aloy", "Who?"))               # below min_words
    assert match_lines.match_all([_tx("c0", "who")], script) == []


def test_tier2_for_mid_score_match():
    script = _script(("Aloy", "We are not going to let that happen here"))
    [b] = match_lines.match_all([_tx("c0", "We are not gonna let that happen")], script)
    assert b.script_index == 0
    assert b.tier == "2"                             # ASR variance -> 80s band
    assert b.transcript == "We are not gonna let that happen"
