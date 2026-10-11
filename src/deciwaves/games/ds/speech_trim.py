"""Pure speech-region keep-span logic for cutscene trim. No ffmpeg/whisperx.

Given WhisperX speech segments for a cutscene whole-scene track, produce the
padded/merged intervals to KEEP (dropping grunt-after-grunt / dead-air between
them), or flag the whole track for dropping when it carries essentially no
dialogue. See docs/architecture.md's "Death Stranding: Director's Cut" section
for how this fits into the cutscene-audio pipeline.

Checking a keep-span row for truncation: compare its kept duration against the
DECODED TRACK LENGTH (`kept_fraction` / `looks_truncated`), never against the
scene's subtitle word count and never via `speech_ratio`. The catalog holds more
subtitle lines than a whole-scene track actually voices (alternate takes,
variants), so words / rate over-estimates the expected duration and flags healthy
rows; and `speech_ratio` is speech / total, so it stays low on a track whose
padded, merged kept span is still essentially the whole track. `sq_cs00_s00100`
is the reference case: speech_ratio 0.132, yet it keeps 24.7 s of a 25.8 s track.
The track length is not stored in the keep-spans CSV (spans are clamped to it,
not recorded with it), so a caller has to decode the track to get it -- the check
is not free, and belongs behind an explicit opt-in rather than any default path.
"""
from __future__ import annotations


def keep_spans(segments, total, pad=0.35, merge_gap=0.5, min_speech=1.0):
    """(spans, dropped) for a track. `segments` = iterable of (start, end) speech
    intervals (s); `total` = track duration (s). Drop (spans=[], dropped=True) when
    total speech < `min_speech`. Otherwise pad each segment +/-`pad`, clamp to
    [0, total], sort, and merge any two whose gap < `merge_gap`."""
    segs = sorted((float(a), float(b)) for a, b in segments)
    speech = sum(b - a for a, b in segs)
    if speech < min_speech:
        return [], True
    padded = [(max(0.0, a - pad), min(total, b + pad)) for a, b in segs]
    merged = []
    for a, b in padded:
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged, False


def kept_fraction(spans, track_seconds):
    """Share of the decoded track that `spans` keep: sum of span lengths divided
    by `track_seconds` (the track's real decoded duration). See the module
    docstring for why this, not word count or speech_ratio, is the yardstick."""
    if track_seconds <= 0:
        raise ValueError(f"track_seconds must be positive, got {track_seconds!r}")
    return sum(b - a for a, b in spans) / track_seconds


def looks_truncated(spans, track_seconds, min_fraction=0.5):
    """True when `spans` keep less than `min_fraction` of the decoded track.

    A review flag, not a verdict: trimming dead air legitimately removes part of
    a track, so a low fraction says "listen to this one", not "this is broken"."""
    return kept_fraction(spans, track_seconds) < min_fraction


def format_spans(spans):
    """Serialize [(a, b), ...] -> "a:b;c:d" (3 dp). [] -> ""."""
    return ";".join(f"{round(a, 3)}:{round(b, 3)}" for a, b in spans)


def parse_spans(s):
    """Inverse of format_spans. "" -> []."""
    s = (s or "").strip()
    if not s:
        return []
    out = []
    for part in s.split(";"):
        a, b = part.split(":")
        out.append((float(a), float(b)))
    return out
