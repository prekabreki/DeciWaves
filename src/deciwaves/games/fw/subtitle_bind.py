"""FW subtitle fast-path binder: label clips with their EXACT in-game
English subtitle instead of an ASR<->web-script paraphrase.

Every arith-clean dialogue group carries a ``LocalizedTextResource`` per line
(English = index 0). Those subtitles match the audio near-verbatim, BUT their
on-disk order is decoupled from the audio (LSSR) order — so we cannot take the
k-th subtitle as the k-th clip's label (see
``.memories/fw-subtitle-binding.md``). Instead we recover the pairing
WITHIN each group by a greedy ASR<->subtitle assignment: a tiny, high-precision
local match (mean ~96%), not the lossy global match against the 6,860-line web
gamescript. The label is the game's exact text; ASR only disambiguates which
clip each subtitle belongs to.

This gives an exact subtitle per clip for the ~10k cleanly-subtitled lines and
auto-culls barks (which carry no subtitle). It does NOT give speaker — that is a
follow-on (match the exact subtitle to the gamescript, or resolve
``SentenceResource`` refs via the link table).

Output uses the same manifest schema as ``manifest.MANIFEST_COLS`` so
``render.py`` consumes it unchanged (tier ``"S"``).
"""

from __future__ import annotations

import argparse
import csv
import os
import re

from deciwaves.games.fw.manifest import MANIFEST_COLS
from deciwaves.games.hzd.match import normalize

# Subtitle timing/markup tokens like ``<time0.17>``; also strip newline breaks.
_MARKUP = re.compile(r"<[^>]*>")

SUBTITLE_TIER = "S"


def clean_subtitle(s: str) -> str:
    """Strip ``<...>`` markup and collapse all whitespace (incl. ``\\n``) to
    single spaces, returning the trimmed display text."""
    return " ".join(_MARKUP.sub(" ", s).split())


def assign_subtitles(subtitles, transcripts):
    """Greedy one-to-one assignment of a group's subtitles to its clips by ASR
    similarity. Returns ``[(subtitle_idx, clip_idx, score), ...]`` sorted by
    ``clip_idx``. ``min(len(subtitles), len(transcripts))`` pairs at most.

    Strongest-pair-first greedy (each subtitle and each clip used once) — the
    sets are small and near-verbatim, so this matches optimal in practice.
    """
    from rapidfuzz import fuzz
    nsub = [normalize(s) for s in subtitles]
    ntr = [normalize(t) for t in transcripts]
    cand = []
    for i, s in enumerate(nsub):
        if not s:
            continue
        for j, t in enumerate(ntr):
            if not t:
                continue
            cand.append((fuzz.token_sort_ratio(s, t), i, j))
    cand.sort(reverse=True)
    used_sub, used_clip = set(), set()
    pairs = []
    for score, i, j in cand:
        if i in used_sub or j in used_clip:
            continue
        used_sub.add(i)
        used_clip.add(j)
        pairs.append((i, j, score))
    pairs.sort(key=lambda p: p[1])
    return pairs


def build_subtitle_rows(groups, accept=70.0):
    """Manifest rows labeling clips with their exact subtitle.

    ``groups``: ``[{group_id, clips:[{line_id,lssr_index,wav,transcript}],
    subtitles:[str]}]`` — ``clips`` in lssr/audio order, ``subtitles`` raw
    (cleaned here). Rows are ordered by ``(group_id, lssr_index)`` with a running
    ``gamescript_index``. A pairing is kept when its score ``>= accept``, OR when
    the group has exactly one subtitle and one clip (certain regardless of ASR
    quality — the lone subtitle belongs to the lone clip).
    """
    out = []
    for g in sorted(groups, key=lambda g: int(g["group_id"])):
        clips = g["clips"]
        subs = [clean_subtitle(s) for s in g["subtitles"]]
        subs = [s for s in subs if s]
        if not clips or not subs:
            continue
        transcripts = [c.get("transcript", "") for c in clips]
        certain = len(subs) == 1 and len(clips) == 1
        for sub_i, clip_j, score in assign_subtitles(subs, transcripts):
            if not certain and score < accept:
                continue
            c = clips[clip_j]
            out.append({
                "line_id": c["line_id"],
                "wav": c["wav"],
                "speaker": "",
                "subtitle": subs[sub_i],
                "gamescript_index": None,  # filled below (global order)
                "quest": "",
                "tier": SUBTITLE_TIER,
                "score": round(float(score), 1),
                "transcript": c.get("transcript", ""),
            })
    out.sort(key=lambda r: r["line_id"])  # stable within already group-sorted
    for i, r in enumerate(out):
        r["gamescript_index"] = i
    return out


# --- graph glue (install-dependent; covered by the integration test) ----------
def scan_arith_clean_groups(graph, reader, store, transcripts_by_id,
                            en_indices=None, max_objects=None, limit=None):
    """Yield ``{group_id, clips, subtitles}`` for every arith-clean EN group the
    reader can scan. ``transcripts_by_id``: line_id -> transcript str. Fail-soft:
    a group whose scan raises (rare unhandled MsgReadBinary type) is skipped.

    ``limit`` stops after that many groups are yielded (review/sample runs);
    ``max_objects`` skips groups bigger than N objects (the pure-Python walk is
    slow on the giant bark banks and is the throughput bottleneck there).
    """
    from deciwaves.engine.pack.fw_rtti import type_hash
    from deciwaves.engine.pack.fw_object_reader import read_group_spans

    LSSR = type_hash("LocalizedSimpleSoundResource")
    LANGS = 12
    if en_indices is None:
        from deciwaves.engine.pack.fw_fast_extract import english_file_indices
        en_indices = english_file_indices(graph)
    fidx = graph.locators.file_index

    for grp in graph.groups:
        tt = graph.type_table[grp.type_start:grp.type_start + grp.type_count]
        n = int((tt == LSSR).sum())
        if n == 0 or grp.locator_count != LANGS * n:
            continue
        if int(fidx[grp.locator_start]) not in en_indices:
            continue
        if max_objects is not None and grp.num_objects > max_objects:
            continue
        clips = []
        for k in range(n):
            lid = f"g{grp.group_id}_{k:04d}"
            t = transcripts_by_id.get(lid)
            if t is None:
                clips = []
                break
            clips.append({"line_id": lid, "lssr_index": k, "wav": "",
                          "transcript": t})
        if not clips:
            continue
        try:
            caps = reader.scan_group(grp, read_group_spans(graph, store, grp))
        except Exception:
            continue
        subs = [o.fields["_texts"][0]
                for o in caps
                if o.type_name == "LocalizedTextResource" and o.fields.get("_texts")]
        if subs:
            yield {"group_id": grp.group_id, "clips": clips, "subtitles": subs}
            if limit is not None:
                limit -= 1
                if limit <= 0:
                    return


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def types_json_error(path: str) -> str | None:
    """Return an actionable error message if *path* (the BYO Decima RTTI type
    map for Forbidden West) doesn't exist, else ``None``. Kept separate from
    ``main`` so the missing-file message is unit-testable without the rest of
    the (install-dependent) pipeline."""
    if os.path.isfile(path):
        return None
    return (
        f"subtitle-bind: --types-json not found at {path}. This must be a "
        "Decima RTTI type map for Forbidden West, user-supplied (BYO -- this "
        "repo can't ship one). See docs/BYO.md for how to obtain it."
    )


def main(argv=None):  # pragma: no cover - integration glue
    ap = argparse.ArgumentParser(description="FW subtitle fast-path manifest")
    ap.add_argument("--package-dir", required=True,
                    help="FW LocalCacheWinGame/package dir")
    ap.add_argument("--types-json", default="types.json",
                    help="Decima RTTI type map for Forbidden West, user-supplied "
                         "(BYO -- see docs/BYO.md); default: types.json in the "
                         "workspace root")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--transcripts", default="out/fw/transcripts.csv")
    ap.add_argument("--out", default="out/fw/subtitle-manifest.csv")
    ap.add_argument("--accept", type=float, default=70.0,
                    help="min assignment score to keep a multi-line pairing")
    ap.add_argument("--max-objects", type=int, default=None,
                    help="skip groups with more than N objects (perf guard)")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N groups (review/sample runs)")
    a = ap.parse_args(argv)

    err = types_json_error(a.types_json)
    if err:
        print(err)
        return 1

    from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
    from deciwaves.engine.pack.fw_stream import FwStreamStore
    from deciwaves.engine.pack.fw_rtti import TypeRegistry
    from deciwaves.engine.pack.fw_object_reader import GroupReader

    graph = StreamingGraph.from_file(os.path.join(a.package_dir, "streaming_graph.core"))
    reg = TypeRegistry(a.types_json)
    store = FwStreamStore(a.package_dir, graph.files)
    reader = GroupReader(graph, reg)

    clip_index = {r["line_id"]: r for r in _load_csv(a.clip_index)}
    transcripts = {r["line_id"]: r["transcript"] for r in _load_csv(a.transcripts)}

    groups = list(scan_arith_clean_groups(graph, reader, store, transcripts,
                                          max_objects=a.max_objects, limit=a.limit))
    rows = build_subtitle_rows(groups, accept=a.accept)
    # fill WAV paths from the clip-index
    for r in rows:
        r["wav"] = clip_index.get(r["line_id"], {}).get("wav", "")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"groups={len(groups)} labeled={len(rows)} -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
