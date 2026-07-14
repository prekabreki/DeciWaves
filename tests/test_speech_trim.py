from engine.speech_trim import keep_spans, format_spans, parse_spans


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
