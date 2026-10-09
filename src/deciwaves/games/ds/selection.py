"""DS creative line-selection rules (Phase D).

Extracted verbatim from deciwaves.games.ds.story_order.build_playlist as DS's own
selection/dedup rules, factored out into a separately-testable module. In practice
only DS uses it today: HZD does NOT reuse it -- its own structural (A,B)-bucket
join is a genuinely different binding mechanism, not a reuse of these rules (see
docs/architecture.md for how selection fits the shared catalog -> selection ->
story_order -> render pipeline, and why HZD's binding differs).

Rules applied by filter_and_dedup:
  1. Require non-empty subtitle_en (drop empty / whitespace-only / placeholder rows).
  2. Require non-empty wem_path_en (prevents degenerate ".core.stream" with no audio).
  3. Within-scene exact (speaker_name, subtitle_en) dedup -- keep first occurrence,
     drop subsequent exact duplicates of the (scene, speaker_name, subtitle_en) key.
  4. Within-scene normalized dedup. Subtitles are casefolded, whitespace-collapsed
     and apostrophe/quote-canonicalized before comparison, so encoding variants
     (typographic vs ASCII apostrophes, the cp1252 mojibake of a typographic mark)
     of the same line collide. Key: (scene, speaker_name, normalized subtitle).
  5. Within-scene near-duplicate dedup. A line whose normalized text is already
     substantially present in what the same speaker has already said earlier in the
     scene is dropped. This catches Class 2 re-splits: the same content segmented
     across sentence boundaries differently in two places, so neither half matches
     the other half exactly. See the constants below for the measured thresholds.
  6. Cross-scene repeats are KEPT -- same text in a different scene is a distinct beat.
  7. Cutscenes are handled separately by the caller (story_order); do NOT pass
     cutscene rows here.

Every dropped duplicate is appended to dupes_sink (a list). The exact row object is
appended (callers write it straight to a CSV), with a synthetic ``dupe_rule`` field
added in place recording which rule dropped it: ``"exact"``, ``"normalized"`` or
``"near-duplicate"``. Rows dropped for empty subtitle or missing wem_path are NOT
added to the sink (they are silently filtered).
"""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

# Decima placeholder subtitle for null-voice (vr0000_null) lines with no audio stream.
PLACEHOLDER_SUBTITLE = "(none)"

# ---------------------------------------------------------------------------
# Near-duplicate detection thresholds.
#
# Measured 2026-10 on the real DS:DC catalog (26,452 rows; 9,760 in-scope
# non-cutscene rows). The re-split phenomenon lives in the prepper terminal
# response banks and in duplicated mission briefings, where the same lines are
# stored more than once with a different sentence segmentation. Every near-drop
# the chosen constants produced across those categories was sampled against the
# scene and confirmed to be a repeat (e.g. lines_pr202 162/163 re-splitting the
# earlier 40/41, lines_city_2w_238 40/41 re-splitting 33); the cut was ~43 rows
# total, not hundreds.
#
# Why these guards:
# * _NEAR_DUP_MIN_CHARS -- a short line is trivially "contained" in a longer one
#   (asymmetric matching). Below this length a row is only ever dropped by the
#   exact/normalized keys, never eaten by containment.
# * _NEAR_DUP_MIN_MATCH -- only contiguous matching runs of at least this many
#   normalized characters count toward coverage. Without it, a scatter of common
#   words ("for", "you", "everything") can sum to a false positive: it made
#   lines_pr204's "Thanks again, for everything." look like a repeat of an
#   unrelated "Thanks again, Sam. ..." line.
# * _NEAR_DUP_COVERAGE -- fraction of the candidate that must be covered. 0.85
#   is deliberately conservative: a majority of a line reappearing is a repeat,
#   while a continuation adds new content and stays well below it.
# * _NEAR_DUP_EXCLUDED_CATEGORIES -- ``common`` is the radio/global instruction
#   bank, where one template repeats with a substituted destination ("Head to
#   <place> and pick it up when you can."). Coverage matching there merges
#   distinct instructions -- measured at 10 such false drops -- so near-duplicate
#   detection is scoped to the in-world dialogue categories (mission/terminal/npc).
#   Encoding-variant (normalized) dedup still applies to radio.
# ---------------------------------------------------------------------------
_NEAR_DUP_MIN_CHARS = 25
_NEAR_DUP_MIN_MATCH = 12
_NEAR_DUP_COVERAGE = 0.85
_NEAR_DUP_EXCLUDED_CATEGORIES = frozenset({"common"})

# Apostrophe/quote variants mapped to one canonical ASCII form so encoding variants
# collide. Includes typographic (U+2019/U+201C...), fullwidth and prime marks.
_QUOTE_TRANSLATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u00b4": "'", "\u0060": "'",
    "\uff07": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u00ab": '"', "\u00bb": '"', "\uff02": '"',
})

# cp1252 mis-decoding of the UTF-8 bytes of a typographic mark ("mojibake"):
# e.g. U+2019 -> E2 80 99 -> "\u00e2\u20ac\u2122". Replaced as substrings before
# the single-character translation above.
_MOJIBAKE_TRANSLATION = {
    "\u00e2\u20ac\u2122": "'", "\u00e2\u20ac\u02dc": "'",
    "\u00e2\u20ac\u0153": '"', "\u00e2\u20ac\u009d": '"',
}


def _normalize(text):
    """Casefold, collapse all whitespace, canonicalize apostrophe/quote variants."""
    normalized = (text or "").casefold()
    for mojibake, replacement in _MOJIBAKE_TRANSLATION.items():
        normalized = normalized.replace(mojibake, replacement)
    normalized = normalized.translate(_QUOTE_TRANSLATION)
    return " ".join(normalized.split())


def _is_near_duplicate(normalized, prior_text):
    """True when ``normalized`` is substantially covered by ``prior_text``.

    Coverage is the fraction of the candidate's characters that are part of an
    exact contiguous match of at least ``_NEAR_DUP_MIN_MATCH`` characters in the
    earlier text. Long enough to require real shared content, loose enough to
    survive a re-split's re-joined sentence boundary.
    """
    if len(normalized) < _NEAR_DUP_MIN_CHARS or not prior_text:
        return False
    blocks = SequenceMatcher(None, normalized, prior_text, autojunk=False).get_matching_blocks()
    covered = sum(b.size for b in blocks if b.size >= _NEAR_DUP_MIN_MATCH)
    return covered / len(normalized) >= _NEAR_DUP_COVERAGE


def _record_drop(row, rule, dupes_sink):
    """Append the exact row object, tagging which rule dropped it."""
    row["dupe_rule"] = rule
    dupes_sink.append(row)


def filter_and_dedup(rows, *, dupes_sink) -> list:
    """Apply DS creative selection rules to catalog rows.

    Parameters
    ----------
    rows:
        Iterable of catalog row dicts (non-cutscene, in-scope rows -- the caller
        is responsible for removing cutscene rows and out-of-scope rows before
        calling this function).
    dupes_sink:
        A list that receives every row dropped as a within-scene duplicate (the
        exact row object, with a ``dupe_rule`` field added). Rows dropped for
        empty subtitle or missing wem_path are NOT added here (they are silently
        filtered).

    Returns
    -------
    list
        Filtered, deduped rows in input order.
    """
    seen_exact: set[tuple] = set()
    seen_normalized: set[tuple] = set()
    # Normalized text kept so far, per (scene, speaker) -- what "this speaker has
    # already said" for the near-duplicate check. Kept, not dropped, rows only.
    prior_text: dict[tuple, str] = defaultdict(str)
    result = []

    for r in rows:
        sub = (r["subtitle_en"] or "").strip()
        if not sub or sub == PLACEHOLDER_SUBTITLE:
            continue
        if not (r["wem_path_en"] or "").strip():
            continue

        speaker_key = (r["scene"], r["speaker_name"])

        if (r["scene"], r["speaker_name"], sub) in seen_exact:
            _record_drop(r, "exact", dupes_sink)
            continue

        normalized = _normalize(sub)
        normalized_key = (r["scene"], r["speaker_name"], normalized)
        if normalized_key in seen_normalized:
            _record_drop(r, "normalized", dupes_sink)
            continue

        if (r["category"] not in _NEAR_DUP_EXCLUDED_CATEGORIES
                and _is_near_duplicate(normalized, prior_text[speaker_key])):
            _record_drop(r, "near-duplicate", dupes_sink)
            continue

        seen_exact.add((r["scene"], r["speaker_name"], sub))
        seen_normalized.add(normalized_key)
        prior_text[speaker_key] = (prior_text[speaker_key] + " " + normalized).strip()
        result.append(r)

    return result
