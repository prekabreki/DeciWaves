"""Qt-free coverage-bar model (#69, spec §5.4).

Reads the persisted coverage artifact (issue #63) -- ``out/<game>/coverage.json``, written
by HZD's wem-metadata/bind stages only (DS/FW write none, so the bar hides there). The
cap-skip count is bucket-granular (``buckets_skipped`` -- the number the "Transcribe all"
escalation clears), so it's labelled as ambiguous *groups*, not clips, to stay honest."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageSummary:
    bound: int
    rows: int
    pct: float
    cap_skipped: int   # buckets_skipped: ambiguous groups the cap left untranscribed
    sample_cap: int


def load_coverage(workspace: str, game: str) -> dict | None:
    """Parse ``out/<game>/coverage.json``, or None if absent/corrupt (it's informational)."""
    path = os.path.join(workspace, "out", game, "coverage.json")
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def coverage_summary(payload: dict | None) -> CoverageSummary | None:
    """Summarize the ``bind`` section, or None if bind hasn't written coverage yet."""
    bind = (payload or {}).get("bind")
    if not isinstance(bind, dict):
        return None
    rows = int(bind.get("rows", 0))
    bound = int(bind.get("bound", 0))
    pct = round(bound / rows * 100, 1) if rows else 0.0
    return CoverageSummary(bound=bound, rows=rows, pct=pct,
                           cap_skipped=int(bind.get("buckets_skipped", 0)),
                           sample_cap=int(bind.get("sample_cap", 0)))


def needs_escalation(summary: CoverageSummary) -> bool:
    """True when a sample cap left ambiguous groups untranscribed -> offer "Transcribe all"."""
    return summary.cap_skipped > 0


def format_coverage(summary: CoverageSummary) -> str:
    text = f"{summary.bound:,} / {summary.rows:,} lines bound · {summary.pct:g}%"
    if needs_escalation(summary):
        text += f" · {summary.cap_skipped:,} ambiguous groups untranscribed (capped)"
    return text
