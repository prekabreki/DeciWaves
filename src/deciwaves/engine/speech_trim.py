"""Pure speech-region keep-span logic for cutscene trim. No ffmpeg/whisperx.

Given WhisperX speech segments for a cutscene whole-scene track, produce the
padded/merged intervals to KEEP (dropping grunt-after-grunt / dead-air between
them), or flag the whole track for dropping when it carries essentially no
dialogue. See docs/superpowers/specs/2026-07-06-ds-cutscene-speech-trim-design.md.
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
