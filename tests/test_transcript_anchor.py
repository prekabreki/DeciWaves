# tests/test_transcript_anchor.py
from engine import transcript_anchor as ta


def test_normalize_folds_quotes_case_punctuation():
    assert ta.normalize("The engine's stalled!") == "the engine s stalled"
    assert ta.normalize("  Oh,   HEY... ") == "oh hey"


def test_scene_anchor_returns_median_of_matches():
    idx = {"the engine s stalled": 10, "we are surrounded here": 20, "shut up": 30}
    # two matches at 10 and 20 -> median 15.0; 'shut up' too short to match (<20 chars)
    anchor = ta.scene_anchor(["The engine's stalled!", "We are surrounded here", "Shut up!"], idx)
    assert anchor == 15.0


def test_scene_anchor_none_when_no_match():
    assert ta.scene_anchor(["totally unmatched line here"], {"something else entirely": 1}) is None


def test_build_index_real_file_smoke():
    idx = ta.build_index()
    assert len(idx) > 1000           # transcript is large
    assert all(len(k) >= ta.MIN_LEN for k in idx)
    assert len(set(idx.values())) == len(idx)  # positions unique
