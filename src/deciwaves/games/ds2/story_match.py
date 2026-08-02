"""DS2 ASR-transcript -> gamescript story matcher.

DS2 has no exact subtitles (the object reader is blocked), so it matches the
gamescript against ASR transcripts instead. Each clip's transcript is also its
stand-in "subtitle" for the matcher.

Joins clip-index + transcripts on `line_id` (inner join -- a failed ASR clip is
absent by design), then calls the game-agnostic fuzzy matcher from engine.
Unmatched clips get a narrative position via a measured region -> group ->
lssr_index fallback (tier ``R`` -- see #388 and
``.memories/ds2-story-order-signals.md``).
"""

from __future__ import annotations

import csv
import os
from collections import Counter

from deciwaves.engine.catalog_io import read_csv_rows
from deciwaves.engine.gamescript import parse_file
from deciwaves.engine.subtitle_match import (
    ELLIPSIS_TERMINATORS, build_rows, match_subtitles,
)

# A gamescript_index strictly above every real script line, so orphan groups
# sort after every bound row. Asserted at runtime against the actual max bound
# index to catch a too-small value silently misinterleaving orphans into the
# story (the ⚠ danger zone the issue calls out).
ORPHAN_BASE = 10_000_000

# Region progression order (content-validated — see
# .memories/ds2-story-order-signals.md). `root` is deliberately last: it is
# 38.3% of lines and mixes system/ambient with story — last is the honest
# position. An unrecognised region sorts after `root` rather than crashing.
_REGION_ORDER = ["l100_mex", "l200_aus", "l400_nr1", "l500_nr2",
                 "l600_nr3", "l700_bea", "root"]
REGION_RANK = {r: i for i, r in enumerate(_REGION_ORDER)}


def _region_rank(region: str) -> int:
    return REGION_RANK.get(region, len(_REGION_ORDER))


MANIFEST_COLS = ["line_id", "wav", "speaker", "subtitle", "gamescript_index",
                 "quest", "tier", "score", "transcript"]


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="DS2 ASR-transcript -> gamescript story matcher")
    ap.add_argument("--clip-index", default="out/ds2/clip-index.csv")
    ap.add_argument("--transcripts", default="out/ds2/transcripts.csv")
    ap.add_argument("--gamescript", required=True,
                    help="path to your own Death Stranding 2 gamescript (BYO)")
    ap.add_argument("--out", default="out/ds2/story-manifest.csv")
    ap.add_argument("--strong", type=float, default=90.0)
    ap.add_argument("--accept", type=float, default=80.0)
    ap.add_argument("--min-words", type=int, default=4)
    a = ap.parse_args(argv)

    clips = read_csv_rows(a.clip_index, required=["line_id", "wav", "group_id",
                                                   "lssr_index", "region"])
    txs = read_csv_rows(a.transcripts, required=["line_id", "transcript"])
    tx_map = {r["line_id"]: r["transcript"] for r in txs}

    clip_lookup = {r["line_id"]: r for r in clips}

    # inner join: only clips that have a transcript
    manifest = [{"line_id": r["line_id"], "wav": r["wav"],
                  "subtitle": tx_map[r["line_id"]],
                  "transcript": tx_map[r["line_id"]]}
                for r in clips if r["line_id"] in tx_map]

    script_lines = parse_file(a.gamescript)
    binds = match_subtitles(manifest, script_lines, strong=a.strong,
                            accept=a.accept, min_words=a.min_words,
                            terminators=ELLIPSIS_TERMINATORS)
    bound_rows = build_rows(binds)

    # Bound rows stay byte-identical (same fields, same values). Build the
    # anchor map for unmatched lines in anchored groups.
    bound_ids = {b.line_id for b in binds}
    anchor_of: dict[int, tuple[int, str]] = {}  # group_id -> (gidx, quest)
    bound_idx_max = -1
    for b in binds:
        clip = clip_lookup[b.line_id]
        gid = int(clip["group_id"])
        if gid not in anchor_of or b.gamescript_index < anchor_of[gid][0]:
            anchor_of[gid] = (b.gamescript_index, b.quest)
        if b.gamescript_index > bound_idx_max:
            bound_idx_max = b.gamescript_index

    assert ORPHAN_BASE > bound_idx_max, (
        f"ORPHAN_BASE ({ORPHAN_BASE}) must exceed the largest bound "
        f"gamescript_index ({bound_idx_max}), or orphan rows would interleave "
        f"into the story")

    # Unmatched rows: tier R, region-ordered fallback
    unmatched_rows = []
    anchored_count = 0
    orphan_count = 0
    for r in clips:
        lid = r["line_id"]
        if lid not in tx_map or lid in bound_ids:
            continue
        clip = clip_lookup[lid]
        gid = int(clip["group_id"])
        region = clip["region"]
        transcript = tx_map[lid]

        if gid in anchor_of:
            gidx, quest = anchor_of[gid]
            anchored_count += 1
        else:
            gidx = (ORPHAN_BASE + _region_rank(region) * 1_000_000 + gid)
            quest = f"{region} (unmatched)"
            orphan_count += 1

        unmatched_rows.append({
            "line_id": lid,
            "wav": clip["wav"],
            "speaker": "",
            "subtitle": transcript,
            "gamescript_index": gidx,
            "quest": quest,
            "tier": "R",
            "score": "",
            "transcript": transcript,
        })

    # Stable sort: bound rows keep their gamescript_index, unmatched rows add
    # group_id + lssr_index only as tiebreaks (lssr_index orders within a
    # conversation).  CSV row order is the tiebreak for bind_spine's stable
    # sort on gamescript_index — write sorted now.
    all_rows = bound_rows + unmatched_rows
    all_rows.sort(key=lambda r: (int(r["gamescript_index"]),
                                  int(clip_lookup.get(r["line_id"], {}).get("group_id", 0)),
                                  int(clip_lookup.get(r["line_id"], {}).get("lssr_index", 0))))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(all_rows)

    tc = Counter(r["tier"] for r in all_rows)
    quests = len({r["quest"] for r in all_rows})
    print(f"clips={len(clips)} transcripts={len(txs)} joined={len(manifest)} "
          f"script_lines={len(script_lines)} "
          f"bound={len(bound_rows)} tier1={tc['1']} tier2={tc['2']} "
          f"tierR={tc['R']} anchored={anchored_count} orphan={orphan_count} "
          f"quests={quests} -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
