"""FW story weave: pull scene dialogue into the precise reel, skip barks.

The precise matcher (bind.py) binds only lines that fuzzy-match the gamescript, so
it drops short interjections and uncovered lines even inside scenes it DID find.
This recovers them WITHOUT shipping barks: a group with >=2 matched anchors whose
script indices cluster tightly IS a real scene (e.g. the Beta media-portal convo,
anchors 4293-4307); place ALL its clips at that scene's story position, in clip
(lssr) order. Matched clips keep their script speaker+subtitle; unmatched scene
clips get their ASR transcript as the label (tier "W", no speaker).

Bark banks (no anchors, a lone stray anchor, or anchors scattered across the whole
script) are NOT scenes -> only their matched clips survive, the rest are dropped.
This is the story-only answer to "weave the sidequests in, skip the barks".
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import statistics

from deciwaves.games.fw.bind import MANIFEST_COLS

_GROUP_RE = re.compile(r"g(\d+)_")


def _group(line_id: str) -> int:
    return int(_GROUP_RE.match(line_id).group(1))


def build_woven_rows(matched_rows, clip_rows, transcripts_by_id,
                     min_anchors=2, max_span=120, subtitles_by_id=None):
    """Manifest rows: matched lines + clips from confirmed scenes, in story order.

    A "scene" = a group with >= ``min_anchors`` matched clips whose gamescript
    indices span <= ``max_span``. All such a group's transcribed clips are woven
    at the scene's median story position (lssr order). Non-scene groups contribute
    only their matched clips. Returns rows (MANIFEST schema), re-ranked by story
    position into ``gamescript_index``.

    When ``subtitles_by_id`` (line_id -> exact in-game subtitle) is given, woven
    scene clips are labeled with their EXACT subtitle instead of the ASR
    transcript, and a scene clip with no subtitle is dropped (subtitle mode — we
    only ship lines the game actually subtitled). Without it, the legacy ASR
    behavior is used (label = transcript).
    """
    matched_by_id = {r["line_id"]: r for r in matched_rows}
    anchors: dict[int, list[int]] = {}
    for r in matched_rows:
        anchors.setdefault(_group(r["line_id"]), []).append(int(r["gamescript_index"]))

    scene_pos = {}                         # group -> story position (median anchor)
    for g, idxs in anchors.items():
        if len(idxs) >= min_anchors and (max(idxs) - min(idxs)) <= max_span:
            scene_pos[g] = statistics.median(idxs)

    clips_by_group: dict[int, list[dict]] = {}
    for c in clip_rows:
        clips_by_group.setdefault(_group(c["line_id"]), []).append(c)

    items = []                             # (story_pos, group, lssr, row)
    for r in matched_rows:                 # every matched clip is kept
        g = _group(r["line_id"])
        pos = scene_pos.get(g, int(r["gamescript_index"]))
        lssr = next((int(c["lssr_index"]) for c in clips_by_group.get(g, [])
                     if c["line_id"] == r["line_id"]), 0)
        items.append((pos, g, lssr, dict(r)))

    for g, pos in scene_pos.items():       # weave unmatched scene clips
        for c in clips_by_group.get(g, []):
            if c["line_id"] in matched_by_id:
                continue
            t = transcripts_by_id.get(c["line_id"])
            asr = t.get("transcript", "").strip() if t else ""
            if subtitles_by_id is not None:        # subtitle mode: exact label
                label = (subtitles_by_id.get(c["line_id"]) or "").strip()
                if not label:                      # no subtitle -> not shipped
                    continue
                score = "100"
            else:                                  # legacy ASR mode
                label = asr
                if not label:
                    continue
                score = t.get("speech_ratio", "")
            anchor = matched_by_id[next(m["line_id"] for m in matched_rows
                                        if _group(m["line_id"]) == g)]
            items.append((pos, g, int(c["lssr_index"]), {
                "line_id": c["line_id"], "wav": c["wav"], "speaker": "",
                "subtitle": label, "gamescript_index": "",
                "quest": anchor["quest"], "tier": "W", "score": score,
                "transcript": asr}))

    items.sort(key=lambda x: (x[0], x[1], x[2]))
    rows = []
    for rank, (_pos, _g, _lssr, row) in enumerate(items):
        row["gamescript_index"] = rank
        rows.append(row)
    return rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="FW story weave: scene dialogue, no barks")
    ap.add_argument("--manifest", default="out/fw/story-manifest.csv",
                    help="matched anchors (subtitle_match output)")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--transcripts", default="out/fw/transcripts.csv")
    ap.add_argument("--subtitles", default="out/fw/subtitle-manifest-full.csv",
                    help="exact in-game subtitles (subtitle_bind output); when set, "
                         "woven scene clips use exact subtitles, not ASR")
    ap.add_argument("--out", default="out/fw/woven-manifest.csv")
    ap.add_argument("--min-anchors", type=int, default=2)
    ap.add_argument("--max-span", type=int, default=120)
    a = ap.parse_args(argv)

    matched = _load_csv(a.manifest)
    clips = [c for c in _load_csv(a.clip_index) if c["file_index"] in ("15", "16")]
    tx = {r["line_id"]: r for r in _load_csv(a.transcripts)}
    subs = None
    if a.subtitles and os.path.isfile(a.subtitles):
        subs = {r["line_id"]: r["subtitle"] for r in _load_csv(a.subtitles)}
    rows = build_woven_rows(matched, clips, tx, min_anchors=a.min_anchors,
                            max_span=a.max_span, subtitles_by_id=subs)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    tc = Counter(r["tier"] for r in rows)
    print(f"matched={len(matched)} woven_total={len(rows)} "
          f"(t1={tc['1']} t2={tc['2']} woven={tc['W']}) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
