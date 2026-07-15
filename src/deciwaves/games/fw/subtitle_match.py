"""Exact-subtitle -> gamescript matcher (story-reel stage).

The subtitle fast-path (`subtitle_bind`) gives every voiced line its EXACT
in-game English subtitle, but mixed in with barks/ambient/variant lines. The
gamescript (`docs/forbidden_west_gamescript.md`, ~6,860 lines in play order) is
the STORY SPINE. Matching each script line to the clip whose subtitle voices it
does three things at once:

  1. **Filters story from bark** — a bark has no script home, so it never binds.
  2. **Supplies the speaker** — the script attributes each line.
  3. **Supplies near-chronological order** — the script is in play order (main
     quest + sidequests interleaved), so the script index orders the reel.

Crucially we match the EXACT in-game subtitle (not lossy ASR) against the script,
so binds are far more precise/numerous than the superseded ASR-transcript matcher
this replaced. The label we keep is the exact subtitle (authoritative on-screen
text); the script supplies only speaker + quest + order.

Same direction + greedy discipline as that superseded matcher: script -> clip,
each clip used once (collapses re-recorded variants of one beat to a single
clip). DLC has no gamescript -> handled separately (its exact subtitles, group
order).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from deciwaves.games.fw.manifest import MANIFEST_COLS
from deciwaves.games.hzd.match import normalize

# A gamescript "line" is a speaker's whole turn — often several sentences — but
# the game shows one subtitle card per sentence. Split on sentence boundaries so
# the granularity matches the subtitle clips (≈doubles recall vs whole-paragraph
# matching, while keeping token_sort's length-sensitive precision).
_SENTENCE = re.compile(r'(?<=[.!?])\s+(?=["\'(\[]*[A-Z0-9])')


def split_sentences(text: str) -> list[str]:
    """Split a script turn into sentences (kept in order). Always >=1 unit."""
    parts = [p.strip() for p in _SENTENCE.split(text) if p.strip()]
    return parts or [text.strip()]


@dataclass
class StoryBind:
    line_id: str
    wav: str
    speaker: str
    subtitle: str            # EXACT in-game subtitle (the label)
    gamescript_index: int    # story position (script order)
    quest: str
    score: float
    tier: str                # "1" confident (>=strong), "2" likely (>=accept)
    transcript: str


def match_subtitles(manifest_rows, script_lines, strong=90.0, accept=80.0,
                    min_words=4):
    """Bind gamescript lines to subtitle-clips (script->clip, token_sort, dedup).

    ``manifest_rows``: dicts with ``line_id``, ``wav``, ``subtitle`` (exact),
    ``transcript``. Returns `StoryBind`s for bound lines only, in script order.
    A clip binds at most one script line; a script line takes its best free clip
    with score >= ``accept`` (>= ``strong`` => tier "1"). ``min_words`` drops
    short lines on both sides (a 2-word bark would match too many script slots).
    """
    # one matchable unit per script sentence; (index, ordinal) preserves order.
    s_rows = []
    for s in script_lines:
        for ordinal, sent in enumerate(split_sentences(s.text)):
            nrm = normalize(sent)
            if len(nrm.split()) >= min_words:
                s_rows.append((s.index, ordinal, s.speaker, s.quest, nrm))
    c_rows = [(r["line_id"], r.get("wav", ""), r["subtitle"],
               r.get("transcript", ""), normalize(r["subtitle"]))
              for r in manifest_rows
              if len(normalize(r["subtitle"]).split()) >= min_words]
    if not s_rows or not c_rows:
        return []

    M = process.cdist([r[4] for r in s_rows], [r[4] for r in c_rows],
                      scorer=fuzz.token_sort_ratio, workers=-1, dtype=np.uint8)
    best = M.argmax(axis=1)
    best_sc = M[np.arange(len(s_rows)), best]

    # greedy: strongest (script sentence, clip) pair first; each clip used once.
    order = sorted(range(len(s_rows)), key=lambda i: int(best_sc[i]), reverse=True)
    used: set[int] = set()
    scored: list[tuple] = []  # (index, ordinal, StoryBind)
    for i in order:
        sc = int(best_sc[i])
        ci = int(best[i])
        if sc < accept or ci in used:
            continue
        used.add(ci)
        s_idx, ordinal, speaker, quest, _ = s_rows[i]
        cid, wav, subtitle, transcript, _ = c_rows[ci]
        scored.append((s_idx, ordinal, StoryBind(
            cid, wav, speaker, subtitle, s_idx, quest,
            float(sc), "1" if sc >= strong else "2", transcript)))
    # chronological: by script index, then sentence order within the turn.
    scored.sort(key=lambda t: (t[0], t[1]))
    return [b for _, _, b in scored]


def build_rows(binds):
    """`StoryBind`s -> manifest rows (``MANIFEST_COLS``) for the renderer."""
    return [{
        "line_id": b.line_id,
        "wav": b.wav,
        "speaker": b.speaker,
        "subtitle": b.subtitle,
        "gamescript_index": b.gamescript_index,
        "quest": b.quest,
        "tier": b.tier,
        "score": b.score,
        "transcript": b.transcript,
    } for b in binds]


def _load_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):  # pragma: no cover - integration glue
    import argparse
    import csv
    import os
    from collections import Counter

    from deciwaves.games.fw.gamescript import parse_file

    ap = argparse.ArgumentParser(
        description="FW exact-subtitle -> gamescript story matcher")
    ap.add_argument("--manifest", default="out/fw/subtitle-manifest-full.csv",
                    help="subtitle_bind output (exact in-game subtitles)")
    ap.add_argument("--gamescript", default="docs/forbidden_west_gamescript.md")
    ap.add_argument("--out", default="out/fw/story-manifest.csv")
    ap.add_argument("--strong", type=float, default=90.0)
    ap.add_argument("--accept", type=float, default=80.0)
    ap.add_argument("--min-words", type=int, default=4)
    a = ap.parse_args(argv)

    manifest = _load_csv(a.manifest)
    script_lines = parse_file(a.gamescript)
    binds = match_subtitles(manifest, script_lines, strong=a.strong,
                            accept=a.accept, min_words=a.min_words)
    rows = build_rows(binds)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    tc = Counter(r["tier"] for r in rows)
    quests = len({r["quest"] for r in rows})
    print(f"subtitles={len(manifest)} script_lines={len(script_lines)} "
          f"bound={len(rows)} tier1={tc['1']} tier2={tc['2']} "
          f"quests={quests} -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
