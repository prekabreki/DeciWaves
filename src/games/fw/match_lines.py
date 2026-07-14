"""FW matcher (#34 step 3): bind each gamescript line to its clip.

Direction matters. The gamescript (~6,860 lines) is the STORY SPINE; for each
script line we find the clip that voices it (script -> clip), NOT the reverse.
Matching clip -> script fails: most of the 61k clips are barks with no script
home, and `token_set_ratio` rewards subsets in both directions, so a bark's two
words subset-match a long line at 100 and corrupt the pick. Script -> clip with
`token_sort_ratio` (full-string, order-normalised, length-sensitive — no subset
reward) instead nails distinctive lines and ignores barks.

Each matched line supplies the clip's speaker + subtitle + story position (its
index). Greedy dedup keeps each clip serving one line (we're reconstructing the
script). Validated on the full ASR set: tier 1 (>=90) ~99% precise, tier 2
(>=80) ~85%; below ~80 ASR-variance false positives dominate, so it's dropped.
Recall is bounded here (short/variant lines miss) — a later group-contiguity
rescue can lift it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from games.hzd.match import normalize


@dataclass
class LineBind:
    line_id: str            # clip id (from clip-index)
    script_index: int | None
    speaker: str
    subtitle: str
    score: float
    tier: str               # "1" confident (>=strong), "2" likely (>=accept)
    transcript: str


def match_all(transcripts, script_lines, strong=90.0, accept=80.0, min_words=4):
    """Bind substantive gamescript lines to clips (script->clip, token_sort, dedup).

    Returns `LineBind`s for bound lines only, in script order. ``min_words`` drops
    short lines/clips (unmatchable without context). Score >= ``accept`` to bind;
    >= ``strong`` is tier "1", else tier "2".
    """
    s_rows = [(s.index, s.speaker, s.text, normalize(s.text)) for s in script_lines
              if len(normalize(s.text).split()) >= min_words]
    c_rows = [(t["line_id"], t["transcript"], normalize(t["transcript"])) for t in transcripts
              if len(normalize(t["transcript"]).split()) >= min_words]
    if not s_rows or not c_rows:
        return []

    M = process.cdist([r[3] for r in s_rows], [r[2] for r in c_rows],
                      scorer=fuzz.token_sort_ratio, workers=-1, dtype=np.uint8)
    best = M.argmax(axis=1)
    best_sc = M[np.arange(len(s_rows)), best]

    # greedy: strongest (line, clip) first; each clip used once
    order = sorted(range(len(s_rows)), key=lambda i: int(best_sc[i]), reverse=True)
    used: set[int] = set()
    binds: list[LineBind] = []
    for i in order:
        sc = int(best_sc[i])
        ci = int(best[i])
        if sc < accept or ci in used:
            continue
        used.add(ci)
        idx, speaker, subtitle, _ = s_rows[i]
        cid, traw, _ = c_rows[ci]
        binds.append(LineBind(cid, idx, speaker, subtitle, float(sc),
                              "1" if sc >= strong else "2", traw))
    binds.sort(key=lambda b: b.script_index)
    return binds
