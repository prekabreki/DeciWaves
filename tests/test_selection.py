"""Tests for engine.selection.filter_and_dedup — the portable creative rules.

Rules (source of truth: .memories/phase-d-line-selection.md):
  (a) Require non-empty subtitle_en (drop empty/whitespace-only/placeholder rows).
  (b) Require non-empty wem_path_en (prevents degenerate ".core.stream" with no audio).
  (c) Within-scene exact (speaker_name, subtitle_en) dedup — keep first, drop rest.
  (d) Cross-scene repeats KEPT (same text in different scenes is a distinct beat).
  (e) Cutscenes are NOT passed to filter_and_dedup — story_order handles them separately.
  (f) Dropped duplicates are recorded by appending to dupes_sink.

These rules are extracted verbatim from deciwaves.engine.story_order.build_playlist.
"""
from deciwaves.engine.selection import filter_and_dedup, PLACEHOLDER_SUBTITLE


def _row(**kw):
    """Minimal in-scope, non-cutscene catalog row."""
    base = dict(
        line_id="id",
        core_path="c",
        line_index="0",
        category="terminal",
        scene="lines_pr201",
        speaker_code="",
        speaker_name="The Engineer",
        subtitle_en="Hello there friend.",
        wem_path_en="loc/x.wem.english",
        language="english",
    )
    base.update(kw)
    return base


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
# (d) Cross-scene repeats KEPT
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
# (e) dupes_sink receives dropped duplicate rows (not empty-subtitle/wem rows)
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
