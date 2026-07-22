"""Full 16.7h subtitled-reel assembler — FW's HZD-scale deliverable.

Ships EVERY exact-subtitled line (subtitle_bind output), ordered by the best
signal available, rather than the precision-bounded ~6h woven story:

  * anchored groups — those containing >=1 line matched to the gamescript
    (`subtitle_match`) — sit at their group's story position (median anchor
    gamescript index), with all the group's clips traveling together in lssr
    (dialogue) order, so scenes stay intact;
  * unanchored base groups follow as scene-clustered blocks (no story signal ->
    group order; labeled "(unsorted scenes)");
  * DLC (Burning Shores) lines sort last as the post-game epilogue.

Matched lines keep their gamescript speaker + quest + tier; every other line
keeps its exact in-game subtitle (tier "S", no speaker). This is the honest
HZD-parity-scale reel: ~16.7h, exact labels, near-chronological where the script
reaches and scene-clustered elsewhere. (Per-line speaker for the unmatched
majority needs SentenceResource ref resolution.)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import statistics

from deciwaves.engine.catalog_io import read_csv_rows
from deciwaves.games.fw.manifest import MANIFEST_COLS
from deciwaves.games.fw.subtitle_bind import DEFAULT_OUT as _SUBTITLE_MANIFEST

_LINE_RE = re.compile(r"g(\d+)_(\d+)")

UNSORTED_QUEST = "(unsorted scenes)"
DLC_QUEST = "Burning Shores (Epilogue)"


def _gk(line_id):
    m = _LINE_RE.match(line_id)
    return int(m.group(1)), int(m.group(2))   # (group_id, lssr_index)


def build_full_reel(subtitle_rows, anchor_rows, dlc_line_ids,
                    unsorted_quest=UNSORTED_QUEST, dlc_quest=DLC_QUEST,
                    unsorted_chunk=2000):
    """Order every subtitled line into one continuous reel (see module docstring).

    ``subtitle_rows``: subtitle_bind manifest rows (exact subtitle per line).
    ``anchor_rows``: subtitle_match story manifest (line_id -> speaker/quest/
    gamescript_index/tier). ``dlc_line_ids``: set of DLC line_ids (file_index 101).
    Returns ``(rows, anchored_count)``: ``rows`` are manifest rows (``MANIFEST_COLS``)
    with a continuous ``gamescript_index``; ``anchored_count`` is how many of them
    landed in a real gamescript-anchored scene (bucket 0) -- the caller's own
    "story-positioned" count must use this, not a ``quest``-string comparison,
    since unanchored rows get a distinct per-chunk quest string below.
    """
    anchor_by_id = {r["line_id"]: r for r in anchor_rows}
    # group -> story position (median of its anchors' gamescript indices)
    group_idxs: dict[int, list[int]] = {}
    for r in anchor_rows:
        g, _ = _gk(r["line_id"])
        group_idxs.setdefault(g, []).append(int(r["gamescript_index"]))
    group_pos = {g: statistics.median(v) for g, v in group_idxs.items()}
    # a scene's quest (any anchor's) so its unmatched scene-mates pack with it
    group_quest: dict[int, str] = {}
    for r in anchor_rows:
        g, _ = _gk(r["line_id"])
        group_quest.setdefault(g, r["quest"])

    items = []   # (bucket, primary, group, lssr, row)
    for s in subtitle_rows:
        lid = s["line_id"]
        g, lssr = _gk(lid)
        row = dict(s)
        a = anchor_by_id.get(lid)
        if a:                                  # matched: carry script metadata
            row["speaker"] = a["speaker"]
            row["quest"] = a["quest"]
            row["tier"] = a["tier"]
        if lid in dlc_line_ids:                # DLC epilogue, sorts last
            row["quest"] = dlc_quest
            items.append((2, 0.0, g, lssr, row))
        elif g in group_pos:                   # anchored scene, chronological
            if not a:
                row["quest"] = group_quest.get(g) or unsorted_quest
            items.append((0, group_pos[g], g, lssr, row))
        else:                                  # unanchored base scene block
            if not a:
                row["quest"] = unsorted_quest
            items.append((1, 0.0, g, lssr, row))

    items.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    out = []
    n_unsorted = 0
    anchored_count = 0
    for rank, (bucket, _p, _g, _l, row) in enumerate(items):
        if bucket == 0:
            anchored_count += 1
        elif bucket == 1:  # chunk the unsorted block into <=290MB-able episodes
            row["quest"] = f"(unsorted scenes {n_unsorted // unsorted_chunk + 1})"
            n_unsorted += 1
        row["gamescript_index"] = rank
        out.append({k: row.get(k, "") for k in MANIFEST_COLS})
    return out, anchored_count


def main(argv=None):  # pragma: no cover - integration glue
    ap = argparse.ArgumentParser(description="FW full 16.7h subtitled reel assembler")
    ap.add_argument("--subtitles", default=_SUBTITLE_MANIFEST)
    ap.add_argument("--anchors", default="out/fw/story-manifest.csv")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--out", default="out/fw/full-reel-manifest.csv")
    a = ap.parse_args(argv)

    subs = read_csv_rows(a.subtitles)
    anchors = read_csv_rows(a.anchors)
    dlc = {r["line_id"] for r in read_csv_rows(a.clip_index) if r.get("file_index") == "101"}
    rows, anchored = build_full_reel(subs, anchors, dlc)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    tc = Counter(r["tier"] for r in rows)
    print(f"subtitles={len(subs)} dlc={len(dlc)} -> reel={len(rows)} rows "
          f"(tiers={dict(tc)}; story-positioned={anchored}) -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
