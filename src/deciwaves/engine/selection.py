"""Portable creative line-selection rules (Phase D).

Extracted verbatim from deciwaves.games.ds.story_order.build_playlist as DS's own
selection/dedup rules, factored out into a separately-testable module. In practice
only DS uses it today: HZD does NOT reuse it -- its own structural (A,B)-bucket
join is a genuinely different binding mechanism, not a reuse of these rules (see
docs/architecture.md for how selection fits the shared catalog -> selection ->
story_order -> render pipeline, and why HZD's binding differs).

Rules applied by filter_and_dedup:
  1. Require non-empty subtitle_en (drop empty / whitespace-only / placeholder rows).
  2. Require non-empty wem_path_en (prevents degenerate ".core.stream" with no audio).
  3. Within-scene exact (speaker_name, subtitle_en) dedup — keep first occurrence,
     drop subsequent duplicates of the same (scene, speaker_name, subtitle_en) key.
  4. Cross-scene repeats are KEPT — same text in a different scene is a distinct beat.
  5. Cutscenes are handled separately by the caller (story_order); do NOT pass
     cutscene rows here.  Dropped duplicates are appended to dupes_sink (a list).
"""
from __future__ import annotations

# Decima placeholder subtitle for null-voice (vr0000_null) lines with no audio stream.
PLACEHOLDER_SUBTITLE = "(none)"


def filter_and_dedup(rows, *, dupes_sink) -> list:
    """Apply portable creative selection rules to catalog rows.

    Parameters
    ----------
    rows:
        Iterable of catalog row dicts (non-cutscene, in-scope rows — the caller
        is responsible for removing cutscene rows and out-of-scope rows before
        calling this function).
    dupes_sink:
        A list that receives every row dropped as a within-scene duplicate.
        Rows dropped for empty subtitle or missing wem_path are NOT added here
        (they are silently filtered).

    Returns
    -------
    list
        Filtered, deduped rows in input order.
    """
    seen: set[tuple] = set()
    result = []

    for r in rows:
        sub = (r["subtitle_en"] or "").strip()
        if not sub or sub == PLACEHOLDER_SUBTITLE:
            continue
        if not (r["wem_path_en"] or "").strip():
            continue
        key = (r["scene"], r["speaker_name"], sub)
        if key in seen:
            dupes_sink.append(r)
            continue
        seen.add(key)
        result.append(r)

    return result
