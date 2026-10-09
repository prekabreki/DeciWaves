"""Tests for engine.selection.filter_and_dedup — the portable creative rules.

Rules (source of truth: deciwaves.games.ds.selection; see docs/architecture.md for how selection
fits the pipeline):
  (a) Require non-empty subtitle_en (drop empty/whitespace-only/placeholder rows).
  (b) Require non-empty wem_path_en (prevents degenerate ".core.stream" with no audio).
  (c) Within-scene exact (speaker_name, subtitle_en) dedup — keep first, drop rest.
  (d) Within-scene normalized dedup (case/whitespace/apostrophe variants collide).
  (e) Within-scene near-duplicate dedup (re-splits across sentence boundaries).
  (f) Cross-scene repeats KEPT (same text in a different scene is a distinct beat).
  (g) Cutscenes are NOT passed to filter_and_dedup — story_order handles them separately.
  (h) Dropped duplicates are recorded by appending to dupes_sink, tagged with dupe_rule.

These rules are extracted verbatim from deciwaves.games.ds.story_order.build_playlist.
"""
from deciwaves.games.ds.selection import filter_and_dedup, PLACEHOLDER_SUBTITLE
from conftest import catalog_row as _row


# ---------------------------------------------------------------------------
# (a) Subtitle required
# ---------------------------------------------------------------------------

def test_empty_subtitle_dropped():
    dropped = []
    result = filter_and_dedup([_row(subtitle_en="")], dupes_sink=dropped)
    assert result == []
    # Empty-subtitle rows are silently filtered, not logged as dupes
    assert dropped == []


def test_whitespace_only_subtitle_dropped():
    dropped = []
    result = filter_and_dedup([_row(subtitle_en="   ")], dupes_sink=dropped)
    assert result == []
    assert dropped == []


def test_placeholder_subtitle_dropped():
    dropped = []
    result = filter_and_dedup(
        [_row(subtitle_en=PLACEHOLDER_SUBTITLE, wem_path_en="")],
        dupes_sink=dropped,
    )
    assert result == []
    assert dropped == []


# ---------------------------------------------------------------------------
# (b) wem_path_en required
# ---------------------------------------------------------------------------

def test_empty_wem_path_dropped():
    dropped = []
    result = filter_and_dedup([_row(wem_path_en="")], dupes_sink=dropped)
    assert result == []
    assert dropped == []


def test_whitespace_wem_path_dropped():
    dropped = []
    result = filter_and_dedup([_row(wem_path_en="   ")], dupes_sink=dropped)
    assert result == []
    assert dropped == []


# ---------------------------------------------------------------------------
# (c) Within-scene dedup — keep first
# ---------------------------------------------------------------------------

def test_within_scene_dedup_keeps_first():
    rows = [
        _row(line_index="0", subtitle_en="Sam."),
        _row(line_index="1", subtitle_en="Sam."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 1
    assert result[0]["line_index"] == "0"
    assert len(dropped) == 1
    assert dropped[0]["line_index"] == "1"


def test_within_scene_dedup_different_speakers_both_kept():
    rows = [
        _row(speaker_name="Sam", subtitle_en="Hello."),
        _row(speaker_name="Deadman", subtitle_en="Hello."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 2
    assert dropped == []


def test_within_scene_dedup_different_subtitles_both_kept():
    rows = [
        _row(subtitle_en="Hello.", speaker_name="Sam"),
        _row(subtitle_en="Goodbye.", speaker_name="Sam"),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 2
    assert dropped == []


# ---------------------------------------------------------------------------
# (f) Cross-scene repeats KEPT
# ---------------------------------------------------------------------------

def test_cross_scene_repeat_kept():
    rows = [
        _row(scene="lines_pr201", subtitle_en="Sam."),
        _row(scene="lines_pr202", subtitle_en="Sam."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 2
    assert dropped == []


def test_cross_scene_same_speaker_same_subtitle_both_kept():
    rows = [
        _row(scene="lines_pr201", speaker_name="Deadman", subtitle_en="Thank you."),
        _row(scene="lines_amelie", speaker_name="Deadman", subtitle_en="Thank you."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 2
    assert dropped == []


# ---------------------------------------------------------------------------
# (h) dupes_sink receives dropped duplicate rows (not empty-subtitle/wem rows)
# ---------------------------------------------------------------------------

def test_dupes_sink_receives_exact_row_object():
    row_a = _row(line_index="0", subtitle_en="Repeated.")
    row_b = _row(line_index="1", subtitle_en="Repeated.")
    dropped = []
    filter_and_dedup([row_a, row_b], dupes_sink=dropped)
    assert dropped == [row_b]


def test_dupes_sink_multiple_drops():
    rows = [
        _row(line_index="0", subtitle_en="Sam."),
        _row(line_index="1", subtitle_en="Sam."),
        _row(line_index="2", subtitle_en="Sam."),
    ]
    dropped = []
    filter_and_dedup(rows, dupes_sink=dropped)
    assert len(dropped) == 2


def test_empty_subtitle_not_logged_to_sink():
    """Empty-subtitle rows are filtered, not treated as kept-first — they don't log dupes."""
    rows = [
        _row(line_index="0", subtitle_en=""),
        _row(line_index="1", subtitle_en=""),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert result == []
    assert dropped == []


# ---------------------------------------------------------------------------
# Good path — valid rows pass through unchanged
# ---------------------------------------------------------------------------

def test_valid_row_passes_through():
    row = _row()
    dropped = []
    result = filter_and_dedup([row], dupes_sink=dropped)
    assert result == [row]
    assert dropped == []


def test_multiple_valid_rows_all_pass():
    rows = [_row(line_index=str(i), subtitle_en=f"Line {i}.") for i in range(5)]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 5
    assert dropped == []


# ---------------------------------------------------------------------------
# (d) Normalized dedup — encoding variants collide
# ---------------------------------------------------------------------------

def test_apostrophe_variant_dropped():
    """Class 1: the same line with a typographic vs ASCII apostrophe is one line."""
    rows = [
        _row(line_index="0", subtitle_en="It's a miracle it made it this far."),
        _row(line_index="1", subtitle_en="It\u2019s a miracle it made it this far."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0"]
    assert [r["line_index"] for r in dropped] == ["1"]
    assert dropped[0]["dupe_rule"] == "normalized"


def test_mojibake_apostrophe_variant_dropped():
    """Class 1: cp1252-mis-decoded typographic apostrophe is the same line."""
    rows = [
        _row(line_index="0", subtitle_en="It's a miracle it made it this far."),
        _row(line_index="1", subtitle_en="It\u00e2\u20ac\u2122s a miracle it made it this far."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0"]
    assert [r["line_index"] for r in dropped] == ["1"]
    assert dropped[0]["dupe_rule"] == "normalized"


def test_case_and_whitespace_variant_dropped():
    rows = [
        _row(line_index="0", subtitle_en="Come  back   soon."),
        _row(line_index="1", subtitle_en="come back soon."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0"]
    assert [r["line_index"] for r in dropped] == ["1"]
    assert dropped[0]["dupe_rule"] == "normalized"


def test_punctuation_only_difference_is_not_a_duplicate():
    """Normalization covers case/whitespace/quotes but not other punctuation."""
    rows = [
        _row(line_index="0", subtitle_en="Hello, Sam!"),
        _row(line_index="1", subtitle_en="Hello, Sam."),
    ]
    dropped = []
    filter_and_dedup(rows, dupes_sink=dropped)
    assert dropped == []


# ---------------------------------------------------------------------------
# (e) Near-duplicate dedup — Class 2 re-splits, with continuations preserved
# ---------------------------------------------------------------------------

def test_resplit_across_sentence_boundaries_dropped():
    """Class 2: the same content split differently elsewhere in the scene.

    The first pair is the original; the second pair re-splits the two sentences
    across different boundaries, so no half matches the other half exactly.
    """
    rows = [
        _row(line_index="0", subtitle_en="We can't make it on our own."),
        _row(line_index="1", subtitle_en=(
            "I think I knew that deep down, after a lifetime of trying..."
            "but it took you to make me admit it.")),
        _row(line_index="2", subtitle_en=(
            "We can't make it on our own. Think I knew that deep down, "
            "after a lifetime of trying...")),
        _row(line_index="3", subtitle_en="But it took you to make me admit it."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0", "1"]
    assert [r["line_index"] for r in dropped] == ["2", "3"]
    assert all(r["dupe_rule"] == "near-duplicate" for r in dropped)


def test_continuation_not_dropped():
    """A line that continues (rather than repeats) the previous one survives."""
    rows = [
        _row(line_index="0", subtitle_en="Well... figure it's my turn to be useful. And if I share my data,"),
        _row(line_index="1", subtitle_en=(
            "if I share my knowledge and memories with you\u2014you'll use it to help "
            "other folks like me, right?")),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0", "1"]
    assert dropped == []


def test_short_line_contained_in_longer_line_kept():
    """Asymmetric matching guard: a short line is never eaten by containment."""
    rows = [
        _row(line_index="0", subtitle_en="So long as I'm still around to welcome you, I will."),
        _row(line_index="1", subtitle_en="I will."),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0", "1"]
    assert dropped == []


def test_near_duplicate_requires_same_speaker():
    """A re-split repeated by a different speaker is a distinct beat and stays."""
    rows = [
        _row(line_index="0", speaker_name="Sam", subtitle_en="We can't make it on our own."),
        _row(line_index="1", speaker_name="Deadman", subtitle_en=(
            "We can't make it on our own. Think I knew that deep down, "
            "after a lifetime of trying...")),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0", "1"]
    assert dropped == []


def test_cross_scene_resplit_kept():
    """Near-duplicate matching is within-scene only."""
    rows = [
        _row(scene="lines_pr201", subtitle_en="We can't make it on our own."),
        _row(scene="lines_pr202", subtitle_en=(
            "We can't make it on our own. Think I knew that deep down, "
            "after a lifetime of trying...")),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert len(result) == 2
    assert dropped == []


def test_radio_template_variant_kept():
    """The radio instruction bank repeats a template with a substituted place.

    Near-duplicate matching is scoped away from ``common`` (radio/global) so two
    distinct instructions are not collapsed into one.
    """
    rows = [
        _row(line_index="0", category="common", scene="lines_radio_nxt", speaker_name="Deadman",
             subtitle_en="Would you mind heading to the distro center south of Lake Knot City "
                         "to pick it up?"),
        _row(line_index="1", category="common", scene="lines_radio_nxt", speaker_name="Deadman",
             subtitle_en="Would you mind heading to Lake Knot City to pick it up?"),
    ]
    dropped = []
    result = filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["line_index"] for r in result] == ["0", "1"]
    assert dropped == []


def test_dupe_rule_records_which_rule_dropped():
    rows = [
        _row(line_index="0", subtitle_en="Sam."),
        _row(line_index="1", subtitle_en="Sam."),                              # exact
        _row(line_index="2", subtitle_en="It's a miracle it made it this far."),
        _row(line_index="3", subtitle_en="It\u2019s a miracle it made it this far."),  # normalized
        _row(line_index="4", subtitle_en="We can't make it on our own."),
        _row(line_index="5", subtitle_en=(
            "I think I knew that deep down, after a lifetime of trying..."
            "but it took you to make me admit it.")),
        _row(line_index="6", subtitle_en=(
            "We can't make it on our own. Think I knew that deep down, "
            "after a lifetime of trying...")),                                  # near-duplicate
    ]
    dropped = []
    filter_and_dedup(rows, dupes_sink=dropped)
    assert [r["dupe_rule"] for r in dropped] == ["exact", "normalized", "near-duplicate"]


def test_dupes_sink_row_is_the_exact_input_object():
    row_a = _row(line_index="0", subtitle_en="Repeated.")
    row_b = _row(line_index="1", subtitle_en="Repeated.")
    dropped = []
    filter_and_dedup([row_a, row_b], dupes_sink=dropped)
    assert dropped[0] is row_b
    assert dropped[0]["dupe_rule"] == "exact"

