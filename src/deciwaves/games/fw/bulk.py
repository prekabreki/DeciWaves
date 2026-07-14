"""FW comprehensive bulk reel (#34 hybrid): ASR-label ALL base clips.

The gamescript only cleanly labels ~1-2.5h (see match_lines); the rest of FW's
~37h of voice has no script home. The hybrid deliverable pairs the precise story
reel with this rough bulk dump: every substantive base clip (file_index 15/16),
labeled by its ASR transcript (no speaker), ordered by group then clip sequence
(scene-clustered, but not story order). Clips already in the precise reel are
excluded so the two are complementary.

`quest` is set to the group id so each group becomes a render episode — that lets
the packer split the ~37h into <=290 MB files (a single quest can't be split).
Same manifest schema as `bind.py`; render with `--tiers B --uniform-mono`.
"""

from __future__ import annotations

import argparse
import csv

from deciwaves.games.fw.bind import MANIFEST_COLS

BASE_FILE_INDICES = {"15", "16"}        # en base + base overflow (101 = DLC, separate)
BULK_TIER = "B"


def build_bulk_rows(clips, transcripts_by_id, exclude=frozenset()):
    """ASR-labeled rows for base clips, ordered group then lssr, excluding `exclude`."""
    rows = []
    for c in sorted(clips, key=lambda c: (int(c["group_id"]), int(c["lssr_index"]))):
        if c["line_id"] in exclude:
            continue
        t = transcripts_by_id.get(c["line_id"])
        if not t or not t.get("transcript", "").strip():
            continue
        rows.append({
            "line_id": c["line_id"],
            "wav": c["wav"],
            "speaker": "",
            "subtitle": t["transcript"].strip(),
            "gamescript_index": len(rows),
            "quest": f"g{c['group_id']}",
            "tier": BULK_TIER,
            "score": t.get("speech_ratio", ""),
            "transcript": t["transcript"].strip(),
        })
    return rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="FW comprehensive ASR-labeled bulk manifest (#34 hybrid)")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--transcripts", default="out/fw/transcripts.csv")
    ap.add_argument("--exclude-manifest", default="out/fw/asr-manifest.csv",
                    help="precise-reel manifest whose line_ids are excluded (complementary dump)")
    ap.add_argument("--out", default="out/fw/bulk-manifest.csv")
    ap.add_argument("--min-words", type=int, default=4,
                    help="drop clips with fewer transcript words (0 = keep all speech)")
    a = ap.parse_args(argv)

    from deciwaves.games.hzd.match import normalize
    clips = [c for c in _load_csv(a.clip_index) if c["file_index"] in BASE_FILE_INDICES]
    tx = {r["line_id"]: r for r in _load_csv(a.transcripts)}
    if a.min_words:
        tx = {k: r for k, r in tx.items()
              if len(normalize(r["transcript"]).split()) >= a.min_words}
    exclude = set()
    try:
        exclude = {r["line_id"] for r in _load_csv(a.exclude_manifest)}
    except FileNotFoundError:
        pass

    rows = build_bulk_rows(clips, tx, exclude=exclude)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"base clips={len(clips)} excluded={len(exclude)} bulk_rows={len(rows)} "
          f"groups={len({r['quest'] for r in rows})} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
