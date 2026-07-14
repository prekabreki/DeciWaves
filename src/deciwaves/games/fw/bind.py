"""FW labeled-manifest writer (match-binding stage): transcripts -> matched manifest.

Joins the matcher output (`LineBind`) with the clip-index (for each clip's WAV
path) and the gamescript (for the quest header) into the labeled manifest that
the renderer consumes. Only bound clips (a matched gamescript line) are written —
the matched line supplies speaker + subtitle + story order (`gamescript_index`).
"""

from __future__ import annotations

import argparse
import csv

from deciwaves.games.fw import match_lines
from deciwaves.games.fw.gamescript import parse_file

MANIFEST_COLS = ["line_id", "wav", "speaker", "subtitle", "gamescript_index",
                 "quest", "tier", "score", "transcript"]


def build_manifest_rows(binds, clip_index, script_lines):
    """Rows for bound clips only, joined with WAV path (clip_index) + quest (script)."""
    quest_by_idx = {sl.index: sl.quest for sl in script_lines}
    rows = []
    for b in binds:
        if b.script_index is None:
            continue
        rows.append({
            "line_id": b.line_id,
            "wav": clip_index.get(b.line_id, {}).get("wav", ""),
            "speaker": b.speaker,
            "subtitle": b.subtitle,
            "gamescript_index": b.script_index,
            "quest": quest_by_idx.get(b.script_index, ""),
            "tier": b.tier,
            "score": b.score,
            "transcript": b.transcript,
        })
    return rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="FW match transcripts -> labeled manifest")
    ap.add_argument("--transcripts", default="out/fw/transcripts.csv")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--gamescript", default="docs/forbidden_west_gamescript.md")
    ap.add_argument("--out", default="out/fw/asr-manifest.csv")
    ap.add_argument("--strong", type=float, default=90.0, help="tier-1 score cutoff")
    ap.add_argument("--accept", type=float, default=80.0, help="min score to bind at all")
    a = ap.parse_args(argv)

    transcripts = _load_csv(a.transcripts)
    clip_index = {r["line_id"]: r for r in _load_csv(a.clip_index)}
    script_lines = parse_file(a.gamescript)
    binds = match_lines.match_all(transcripts, script_lines, strong=a.strong, accept=a.accept)
    rows = build_manifest_rows(binds, clip_index, script_lines)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    tc = Counter(r["tier"] for r in rows)
    print(f"clips={len(transcripts)} bound={len(rows)} "
          f"tier1={tc['1']} tier2={tc['2']} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
