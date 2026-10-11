import pytest

from deciwaves.games.ds.speech_trim import (keep_spans, format_spans, parse_spans,
                                         kept_fraction, looks_truncated)


def test_keep_spans_pads_and_clamps_to_track_bounds():
    spans, dropped = keep_spans([(1.0, 2.0)], total=3.0, pad=0.35, merge_gap=0.5, min_speech=0.5)
    assert dropped is False
    assert spans == [(0.65, 2.35)]


def test_keep_spans_clamps_pad_at_edges():
    spans, dropped = keep_spans([(0.1, 2.9)], total=3.0, pad=0.35, merge_gap=0.5, min_speech=0.5)
    assert spans == [(0.0, 3.0)]  # pad cannot exceed [0, total]


def test_keep_spans_merges_close_regions():
    # gap between padded regions (2.35 -> 2.65 = 0.30) < merge_gap 0.5 => merge
    spans, dropped = keep_spans([(1.0, 2.0), (3.0, 4.0)], total=5.0,
                                pad=0.35, merge_gap=0.5, min_speech=0.5)
    assert spans == [(0.65, 4.35)]


def test_keep_spans_keeps_far_regions_separate():
    spans, dropped = keep_spans([(1.0, 2.0), (4.0, 5.0)], total=6.0,
                                pad=0.35, merge_gap=0.5, min_speech=0.5)
    assert spans == [(0.65, 2.35), (3.65, 5.35)]


def test_keep_spans_drops_track_below_min_speech():
    # total speech 0.4s < min_speech 1.0 => dropped, no spans (pure grunt)
    spans, dropped = keep_spans([(1.0, 1.2), (2.0, 2.2)], total=60.0, min_speech=1.0)
    assert dropped is True
    assert spans == []


def test_keep_spans_empty_transcript_drops():
    spans, dropped = keep_spans([], total=60.0, min_speech=1.0)
    assert (spans, dropped) == ([], True)


def test_format_and_parse_spans_roundtrip():
    spans = [(0.65, 2.35), (3.65, 5.35)]
    assert format_spans(spans) == "0.65:2.35;3.65:5.35"
    assert parse_spans("0.65:2.35;3.65:5.35") == spans


def test_format_empty_and_parse_empty():
    assert format_spans([]) == ""
    assert parse_spans("") == []


# sq_cs00_s00100 as packaged: speech_ratio 0.132, one kept span 0.677:25.423 on a
# 25.8 s decoded track. Its subtitle word count implies far more audio than the
# track holds, which is how a words-vs-duration oracle wrongly called it truncated.
_CS00_SPANS = parse_spans("0.677:25.423")
_CS00_TRACK = 25.8
_CS00_SPEECH_RATIO = 0.132


def test_low_speech_ratio_row_keeping_almost_all_of_its_track_is_not_flagged():
    assert _CS00_SPEECH_RATIO < 0.5  # low enough that a ratio-based check would fire
    assert kept_fraction(_CS00_SPANS, _CS00_TRACK) == pytest.approx(24.746 / 25.8)
    assert looks_truncated(_CS00_SPANS, _CS00_TRACK) is False


def test_row_keeping_a_small_share_of_its_track_is_flagged():
    assert looks_truncated([(0.5, 3.0), (10.0, 12.0)], 25.8) is True  # 4.5 of 25.8 s


def test_kept_fraction_sums_every_span():
    assert kept_fraction([(0.0, 1.0), (2.0, 4.0)], 6.0) == pytest.approx(0.5)


def test_kept_fraction_rejects_non_positive_track_length():
    with pytest.raises(ValueError):
        kept_fraction([(0.0, 1.0)], 0.0)
