"""Anchor a dialogue scene to its position in the in-order game transcript.

A narrative-ordered transcript ("Speaker: text" lines, [] scene breaks) is BYO --
copyrighted game-script prose, not shipped in this repo (see docs/BYO.md). Against
the DS gamescript it matches ~93% of distinctive cutscene subtitles, so a scene's
median matched position is a ground-truth narrative anchor (see the Phase D design doc).
"""
from __future__ import annotations

import re
import statistics
import unicodedata

MIN_LEN = 20
_SPEAKER_RE = re.compile(r"^[A-Z][\w .'-]{0,20}:\s*(.+)$")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def build_index(path: str) -> dict[str, int]:
    index: dict[str, int] = {}
    n = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or re.fullmatch(r"\[.*\]", line):
                continue
            m = _SPEAKER_RE.match(line)
            t = normalize(m.group(1) if m else line)
            if len(t) >= MIN_LEN and t not in index:
                index[t] = n
                n += 1
    return index


def scene_anchor(subtitles: list[str], index: dict[str, int], min_len: int = MIN_LEN) -> float | None:
    positions = []
    for s in subtitles:
        t = normalize(s)
        if len(t) >= min_len and t in index:
            positions.append(index[t])
    return statistics.median(positions) if positions else None
