"""Sentence-terminator selection in `split_sentences` / `match_subtitles` (issue #393).

DS2's gamescript uses U+2026 HORIZONTAL ELLIPSIS as a real sentence boundary; FW's
binding is measured against the ASCII-only set. The terminator set is therefore a
parameter, and these tests pin BOTH sides of that: DS2 opts in, and the default
(what FW gets) is unchanged.
"""
from types import SimpleNamespace

from deciwaves.engine.subtitle_match import (
    DEFAULT_TERMINATORS,
    ELLIPSIS_TERMINATORS,
    match_subtitles,
    split_sentences,
)

# The exact pattern the module used before the terminator set became a parameter.
# If the default ever stops reproducing this, FW's matching has moved.
_HISTORICAL = r'(?<=[.!?])\s+(?=["(\'[]*[A-Z0-9])'

# The real DS2 line that exposed the bug: two utterances, one ellipsis boundary.
_REAL = ("I'm certain he's still alive, and since no one else has taken on the "
         "order as of yet… I hope you'll at least consider it.")


def test_default_terminators_are_ascii_only():
    assert DEFAULT_TERMINATORS == ".!?"
    assert "…" not in DEFAULT_TERMINATORS


def test_default_reproduces_the_historical_regex_exactly():
    """FW's guard: the default splitter must behave like the pre-#393 pattern."""
    import re

    old = re.compile(_HISTORICAL)
    samples = [
        _REAL,
        "One. Two! Three? Four.",
        "Wait... What?",                     # three-dot form already worked
        "Dr. Smith went home. He slept.",
        "No terminators here at all",
        "Ends with an ellipsis…",
        "Quote. \"Then this.\"",
    ]
    for s in samples:
        expected = [p.strip() for p in old.split(s) if p.strip()] or [s.strip()]
        assert split_sentences(s) == expected, s


def test_ellipsis_is_not_a_boundary_by_default():
    assert split_sentences(_REAL) == [_REAL]


def test_ellipsis_splits_when_opted_in():
    parts = split_sentences(_REAL, ELLIPSIS_TERMINATORS)
    assert len(parts) == 2
    assert parts[0].endswith("as of yet…")
    assert parts[1] == "I hope you'll at least consider it."


def test_three_dot_ellipsis_still_splits_under_both_sets():
    text = "That is done... Now we leave."
    for terms in (DEFAULT_TERMINATORS, ELLIPSIS_TERMINATORS):
        assert len(split_sentences(text, terms)) == 2, terms


def test_ellipsis_without_following_capital_does_not_split():
    """The lookahead still governs: `…` mid-phrase is a pause, not a boundary."""
    text = "I was thinking… maybe we wait."
    assert split_sentences(text, ELLIPSIS_TERMINATORS) == [text]


def _line(index, speaker, text, quest="Q"):
    return SimpleNamespace(index=index, speaker=speaker, text=text, quest=quest)


def _clip(line_id, text):
    return {"line_id": line_id, "wav": f"{line_id}.wav",
            "subtitle": text, "transcript": text}


def test_opting_in_binds_the_clip_the_glued_unit_stranded():
    """End to end: the trailing utterance has its own clip, and only binds when
    the ellipsis splits the script unit. This is the #393 gain in miniature."""
    script = [_line(0, "The Adventurer's Son", _REAL)]
    clips = [
        _clip("c1", "I'm certain he's still alive and since no one else has "
                    "taken on the order as of yet,"),
        _clip("c2", "I hope you'll at least consider it."),
    ]

    default_bound = {b.line_id for b in match_subtitles(clips, script)}
    opted_bound = {b.line_id for b in
                   match_subtitles(clips, script, terminators=ELLIPSIS_TERMINATORS)}

    assert "c2" not in default_bound          # stranded today
    assert {"c1", "c2"} <= opted_bound        # both bind once the unit splits


def test_opting_in_raises_the_score_of_the_truncated_bind():
    """The glued unit carries text the clip never says, which depresses its score."""
    script = [_line(0, "S", _REAL)]
    clips = [_clip("c1", "I'm certain he's still alive and since no one else has "
                         "taken on the order as of yet,")]

    (before,) = match_subtitles(clips, script)
    (after,) = match_subtitles(clips, script, terminators=ELLIPSIS_TERMINATORS)
    assert after.score > before.score
