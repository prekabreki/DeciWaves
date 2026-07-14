"""FW Burning Shores DLC reel (#34): label DLC clips from ASR text only.

No gamescript covers the DLC (it predates Burning Shores, and no transcript exists
online), so DLC clips can't be matched/attributed. Instead we ship them as a
separate, rough reel: the ASR transcript IS the on-screen label (no speaker), and
order is clip sequence — within a group by `lssr_index` (~dialogue order), groups
by id (arbitrary but scene-clustered). "Doesn't have to be perfect."

DLC clips are identified structurally by `file_index == 101` (the dlc/en stream;
see fw-batch-extractor-status). Output uses the same manifest schema as `bind.py`
so `render.py` consumes it unchanged (tier "D").
"""

from __future__ import annotations

import argparse
import csv

from deciwaves.games.fw.bind import MANIFEST_COLS

DLC_FILE_INDEX = "101"
DLC_QUEST = "Burning Shores"
DLC_TIER = "D"


def is_dlc(clip_row) -> bool:
    return clip_row.get("file_index") == DLC_FILE_INDEX


def build_dlc_rows(dlc_clips, transcripts_by_id, min_words, quest=DLC_QUEST):
    """Manifest rows for DLC clips, labeled by ASR text, ordered group then lssr.

    ``transcripts_by_id``: line_id -> {transcript, speech_ratio}. Clips with no
    (or blank) transcript are dropped. ``min_words`` culls barks: DLC has no script
    to match, but combat/ambient barks are short ("There.", "Coming in!") while
    story dialogue is longer, so a word-count floor is a serviceable bark filter.
    Required (no default): the CLI defaults it to 6, and a silent function-side
    default of 0 previously meant a direct caller got NO bark filtering — the
    opposite of this module's purpose. Pass min_words=0 explicitly to keep everything.
    """
    from deciwaves.games.hzd.match import normalize
    rows = []
    for c in sorted(dlc_clips, key=lambda c: (int(c["group_id"]), int(c["lssr_index"]))):
        t = transcripts_by_id.get(c["line_id"])
        text = t["transcript"].strip() if t else ""
        if not text or len(normalize(text).split()) < min_words:
            continue
        rows.append({
            "line_id": c["line_id"],
            "wav": c["wav"],
            "speaker": "",
            "subtitle": text,
            "gamescript_index": len(rows),
            "quest": quest,
            "tier": DLC_TIER,
            "score": t.get("speech_ratio", ""),
            "transcript": text,
        })
    return rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="FW DLC ASR-labeled manifest (#34)")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--transcripts", default="out/fw/transcripts.csv")
    ap.add_argument("--out", default="out/fw/dlc-manifest.csv")
    ap.add_argument("--min-words", type=int, default=6,
                    help="cull DLC barks: drop clips with fewer transcript words")
    ap.add_argument("--quest", default="Burning Shores (Epilogue)")
    a = ap.parse_args(argv)

    dlc_clips = [c for c in _load_csv(a.clip_index) if is_dlc(c)]
    tx = {r["line_id"]: r for r in _load_csv(a.transcripts)}
    rows = build_dlc_rows(dlc_clips, tx, min_words=a.min_words, quest=a.quest)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"dlc_clips={len(dlc_clips)} labeled={len(rows)} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
