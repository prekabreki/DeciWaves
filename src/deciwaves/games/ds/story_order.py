"""Phase D ordering: catalog.csv + cutscene_tracks.csv + transcript -> ordered playlist.

Pure/deterministic. Applies the Phase D scope filter, subtitle requirement, and within-scene
dedup (portable rules extracted to deciwaves.engine.selection; see docs/architecture.md for how
selection fits the pipeline). Narrative order is transcript-anchored where the
transcript covers a scene; episode_map heuristics place the rest. Cutscene audio comes from
whole-scene track rows, not per-line.

Invoke as a module (package form):
    python -m deciwaves.games.ds.story_order
"""
from __future__ import annotations

import csv
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass, asdict

from deciwaves.games.ds import episode_map as em
from deciwaves.engine import transcript_anchor as ta
from deciwaves.engine.selection import filter_and_dedup

SECTION = {"cutscene": 0, "mission": 1, "terminal": 2, "npc": 3, "radio": 4}
SPINE = {"cutscene", "mission"}
NPC_KEEP = {"lines_amelie", "lines_artist", "lines_cliff",
            "lines_deadman", "lines_higgs", "lines_mama"}
RADIO_SCENES = {"lines_radio_nxt", "lines_global"}


@dataclass
class Segment:
    episode: int
    is_side: int
    pos: float
    section: int
    scene: str
    line_index: int
    track_index: int
    category: str
    speaker: str
    subtitle: str
    stream_path: str
    line_id: str


def in_scope(category, scene):
    if category in ("cutscene", "mission", "terminal"):
        return True
    if category == "npc":
        return scene in NPC_KEEP
    if category == "common":
        return scene in RADIO_SCENES
    return False


def _section_for(category):
    return SECTION["radio"] if category == "common" else SECTION[category]


_UNPARSEABLE_CS_KEY = 1e6  # sentinel: sorts after every real anchor/hint/cs-number


def order_cutscene_groups(group_anchors):
    """Cutscene groups ordered by transcript anchor; else CS_ORDER_HINT; else the numeric
    cs-number parsed from the group name (e.g. "sq_cs07_..." group "cs07" -> 7), so the
    main story orders numerically and sorts before the hinted extras' ~980+ keys instead
    of tying at a flat sentinel. Group names with no parsable cs-number sort last. The
    group name is an explicit tiebreak, so equal keys still sort deterministically --
    independent of set-iteration order, hash seed, or insertion order."""
    def key(g):
        a = group_anchors.get(g)
        hint = em.CS_ORDER_HINT.get(g)
        if a is not None:
            k = float(a)
        elif hint is not None:
            k = hint
        else:
            n = em.cs_number(g)
            k = float(n) if n is not None else _UNPARSEABLE_CS_KEY
        return (k, g)
    return sorted(group_anchors, key=key)


def _scene_subtitles(catalog_rows):
    subs = defaultdict(list)
    for r in catalog_rows:
        s = (r["subtitle_en"] or "").strip()
        if s:
            subs[(r["category"], r["scene"])].append(s)
    return subs


def build_playlist(catalog_rows, cutscene_rows, anchor_index):
    subs = _scene_subtitles(catalog_rows)

    # 1. per-scene anchors
    scene_anchor = {(cat, sc): ta.scene_anchor(lst, anchor_index)
                    for (cat, sc), lst in subs.items()}

    # 2. cutscene groups present (from catalog cutscene rows + track rows) + their anchors
    groups = set()
    for (cat, sc) in subs:
        if cat == "cutscene" and em.cs_group(sc):
            groups.add(em.cs_group(sc))
    for r in cutscene_rows:
        g = em.cs_group(r["scene"])
        if g:
            groups.add(g)
    group_anchor = {}
    for g in groups:
        vals = [scene_anchor[(cat, sc)] for (cat, sc) in scene_anchor
                if cat == "cutscene" and em.cs_group(sc) == g and scene_anchor[(cat, sc)] is not None]
        group_anchor[g] = statistics.median(vals) if vals else None

    ordered = order_cutscene_groups(group_anchor)
    ep_index = {g: i for i, g in enumerate(ordered)}
    n_eps = max(len(ordered), 1)

    def group_pos(g):
        a = group_anchor.get(g)
        return a if a is not None else em.CS_ORDER_HINT.get(g, ep_index.get(g, 0) * 100.0)

    # group_anchor is fixed above and never mutated again, so this filtered view
    # is loop-invariant -- build it once instead of on every assign_group() call
    # (assign_group runs once per catalog row, below).
    anchored = {g: group_anchor[g] for g in group_anchor if group_anchor[g] is not None}

    def assign_group(cat, sc):
        a = scene_anchor.get((cat, sc))
        if a is not None and anchored:
            return min(anchored, key=lambda g: abs(anchored[g] - a))
        return em.fallback_group(cat, sc)

    segs = []

    # 3. cutscene segments from track rows
    for r in cutscene_rows:
        if r.get("status") != "resolved" or not r.get("voice_track_stream"):
            continue
        sc = r["scene"]
        g = em.cs_group(sc) or "cs00"
        a = scene_anchor.get(("cutscene", sc))
        pos = a if a is not None else group_pos(g) + em.scene_number(sc)[-1] * 1e-3
        segs.append(Segment(
            episode=ep_index.get(g, 0), is_side=0, pos=float(pos),
            section=SECTION["cutscene"], scene=sc, line_index=0,
            track_index=int(r["track_index"] or 0), category="cutscene",
            speaker="(scene)", subtitle="", stream_path=r["voice_track_stream"],
            line_id=f"{sc}#track{r['track_index'] or 0}"))

    # 4. per-line segments (dedup within scene; cutscene per-line rows skipped)
    # Pre-filter: drop cutscene rows and out-of-scope rows before selection.
    in_scope_rows = [r for r in catalog_rows
                     if r["category"] != "cutscene" and in_scope(r["category"], r["scene"])]
    dropped = []
    selected = filter_and_dedup(in_scope_rows, dupes_sink=dropped)

    radio_rows = []
    for r in selected:
        cat, sc = r["category"], r["scene"]
        sub = (r["subtitle_en"] or "").strip()
        if cat == "common":
            radio_rows.append((r, sub))
            continue
        g = assign_group(cat, sc)
        a = scene_anchor.get((cat, sc))
        pos = a if a is not None else group_pos(g) + em.scene_number(sc)[-1] * 1e-3
        segs.append(Segment(
            episode=ep_index.get(g, 0), is_side=1 if cat not in SPINE else 0,
            pos=float(pos), section=_section_for(cat), scene=sc,
            line_index=int(r["line_index"]), track_index=0, category=cat,
            speaker=r["speaker_name"], subtitle=sub,
            stream_path=r["wem_path_en"] + ".core.stream", line_id=r["line_id"]))

    # 5. radio: proportional split per scene by in-core line_index
    by_scene = defaultdict(list)
    for r, sub in radio_rows:
        by_scene[r["scene"]].append((r, sub))
    for sc, items in by_scene.items():
        items.sort(key=lambda rs: int(rs[0]["line_index"]))
        total = len(items)
        for rank, (r, sub) in enumerate(items):
            ep = em.radio_episode(rank, total, n_eps)
            segs.append(Segment(
                episode=ep, is_side=1, pos=float(ep), section=SECTION["radio"],
                scene=sc, line_index=int(r["line_index"]), track_index=0,
                category="common", speaker=r["speaker_name"], subtitle=sub,
                stream_path=r["wem_path_en"] + ".core.stream", line_id=r["line_id"]))

    segs.sort(key=lambda s: (s.episode, s.is_side, s.pos, s.section,
                             em.scene_number(s.scene), s.line_index, s.track_index))
    return segs, dropped


PLAYLIST_COLUMNS = ["episode", "is_side", "pos", "section", "scene", "line_index",
                    "track_index", "category", "speaker", "subtitle", "stream_path", "line_id"]


def write_playlist(segments, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PLAYLIST_COLUMNS)
        w.writeheader()
        for s in segments:
            w.writerow(asdict(s))


def read_playlist(path):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(Segment(
                episode=int(r["episode"]), is_side=int(r["is_side"]), pos=float(r["pos"]),
                section=int(r["section"]), scene=r["scene"], line_index=int(r["line_index"]),
                track_index=int(r["track_index"]), category=r["category"],
                speaker=r["speaker"], subtitle=r["subtitle"],
                stream_path=r["stream_path"], line_id=r["line_id"]))
    return out


def main(argv=None):
    import argparse
    from collections import Counter
    ap = argparse.ArgumentParser(description="Build out/playlist.csv (Phase D order)")
    ap.add_argument("--catalog", default="out/catalog.csv")
    ap.add_argument("--cutscene-tracks", default="out/cutscene_tracks.csv")
    ap.add_argument("--transcript", default="",
                    help="narrative transcript for anchoring (BYO — see docs/BYO.md); "
                         "'' disables anchoring and falls back to episode/scene order")
    ap.add_argument("--out", default="out/playlist.csv")
    ap.add_argument("--dupes", default="out/render-dupes.csv")
    args = ap.parse_args(argv)

    with open(args.catalog, newline="", encoding="utf-8") as f:
        catalog_rows = list(csv.DictReader(f))
    with open(args.cutscene_tracks, newline="", encoding="utf-8") as f:
        cutscene_rows = list(csv.DictReader(f))

    if args.transcript and os.path.isfile(args.transcript):
        anchor_index = ta.build_index(args.transcript)
    else:
        if args.transcript:
            print(f"transcript not found: {args.transcript} -- "
                  f"anchoring disabled (see docs/BYO.md)")
        else:
            print("transcript anchoring disabled (no transcript provided — see docs/BYO.md)")
        anchor_index = {}

    segs, dropped = build_playlist(catalog_rows, cutscene_rows, anchor_index)
    write_playlist(segs, args.out)
    if dropped:
        with open(args.dupes, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(dropped[0].keys()))
            w.writeheader(); w.writerows(dropped)
    elif os.path.isfile(args.dupes):
        # A stale dupes file from an earlier run (back when there WERE dupes)
        # must not linger and look current after a later, clean re-run.
        os.remove(args.dupes)

    by_ep = Counter(s.episode for s in segs)
    print(f"{len(segs)} segments, {len(dropped)} dupes dropped, "
          f"{len(by_ep)} episodes -> {args.out}")
    for ep in sorted(by_ep):
        print(f"  ep {ep:>2}  {by_ep[ep]:5d} segments")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
