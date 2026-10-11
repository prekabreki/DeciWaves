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

Also holds the level gate that finds audio in tracks ASR dropped outright, and
the guard that decides whether its spans may replace a row (see
games.ds.keepspans_check).
"""
from __future__ import annotations

import numpy as np


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


# Level-gate repair of rows ASR dropped while the track still carries audio (#416).
# The gate measures LEVEL, not words: it finds quiet or short utterances ASR misses,
# but cannot tell speech from breathing or ambience and cuts mid-word at every dip.
# Applied to healthy rows it made scenes worse and shattered them into 16-51 spans,
# so it only ever touches `dropped=1` rows, behind `refuse_replacement`.
GATE_DBFS = -50.0   # a window louder than this counts as sound
WINDOW_MS = 20
MIN_KEEP = 0.2      # ignore loud runs shorter than this (s)
MAX_SPANS = 6       # a replacement fragmenting further than this is refused


def gate_spans(samples, rate, gate_dbfs=GATE_DBFS, window_ms=WINDOW_MS, min_keep=MIN_KEEP,
               pad=0.35, merge_gap=0.5):
    """(spans, total) from mono float `samples` in [-1, 1] at `rate` Hz. RMS over
    `window_ms` windows; each contiguous run above `gate_dbfs` lasting >= `min_keep`
    becomes a span padded +/-`pad`, clamped to [0, total], then spans closer than
    `merge_gap` merge. No loud run -> []."""
    a = np.asarray(samples, dtype=np.float64)
    total = len(a) / rate
    win = max(1, int(rate * window_ms / 1000))
    frames = a[: len(a) // win * win].reshape(-1, win)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    loud = 20 * np.log10(np.maximum(rms, 1e-12)) > gate_dbfs
    step = win / rate
    spans = []
    i = 0
    while i < len(loud):
        if not loud[i]:
            i += 1
            continue
        j = i
        while j < len(loud) and loud[j]:
            j += 1
        if (j - i) * step >= min_keep:
            spans.append((max(0.0, i * step - pad), min(total, j * step + pad)))
        i = j
    merged = []
    for a0, b0 in spans:
        if merged and a0 - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b0))
        else:
            merged.append((a0, b0))
    return merged, total


def kept_seconds(spans):
    """Total audio a span list keeps (s)."""
    return sum(b - a for a, b in spans)


def refuse_replacement(new_spans, old_spans, max_spans=MAX_SPANS):
    """Why `new_spans` must NOT replace `old_spans`, or None when it may. A
    replacement must keep strictly more audio than the original and stay within
    `max_spans` spans -- anything else is a level gate cutting up real dialogue."""
    new_kept, old_kept = kept_seconds(new_spans), kept_seconds(old_spans)
    if new_kept <= old_kept:
        return f"keeps {new_kept:.2f}s, not more than the original {old_kept:.2f}s"
    if len(new_spans) > max_spans:
        return f"{len(new_spans)} spans exceeds the {max_spans}-span limit"
    return None
