"""Game-agnostic subtitle/gamescript matching core.

Matches each gamescript line to the clip whose subtitle voices it, doing
three things at once:

  1. **Filters story from bark** -- a bark has no script home, so it never binds.
  2. **Supplies the speaker** -- the script attributes each line.
  3. **Supplies near-chronological order** -- the script is in play order, so the
     script index orders the output.

Matching is per *sentence*: the game shows one subtitle card per sentence while
the gamescript keeps a speaker's whole turn as one line, so sentences are split
to match the clip granularity.

Direction + greedy discipline: script -> clip, each clip used once (collapses
re-recorded variants of one beat to a single clip).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from rapidfuzz import fuzz, process

from deciwaves.engine.text_normalize import normalize

# A gamescript "line" is a speaker's whole turn — often several sentences — but
# the game shows one subtitle card per sentence. Split on sentence boundaries so
# the granularity matches the subtitle clips (≈doubles recall vs whole-paragraph
# matching, while keeping token_sort's length-sensitive precision).
#
# Which characters END a sentence is per-gamescript, not universal, so it is a
# parameter rather than a constant (issue #393). The default is ASCII-only and
# is the historical behaviour: FW's binding is measured against it, so changing
# the default would silently move FW's exact-subtitle matching.
DEFAULT_TERMINATORS = ".!?"

# DS2's gamescript uses U+2026 HORIZONTAL ELLIPSIS as a real sentence boundary
# throughout ("...as of yet… I hope you'll at least consider it."). With the
# ASCII-only set those stay glued into one match unit, which both depresses the
# score (the unit carries text the clip never voices) and strands the following
# clip with nothing to bind to. Measured on the #386 retail run: +196 binds
# (3,572 -> 3,768) and 48 existing binds scoring higher. Three-dot "..." already
# worked, because "." is in the default set; only the single codepoint was missed.
ELLIPSIS_TERMINATORS = ".!?…"


@lru_cache(maxsize=8)
def _sentence_re(terminators: str) -> re.Pattern:
    """Compiled splitter for a terminator set. Cached: `match_subtitles` calls
    `split_sentences` once per script line, and recompiling per call is waste."""
    return re.compile(rf'(?<=[{re.escape(terminators)}])\s+(?=["(\'[]*[A-Z0-9])')


def split_sentences(text: str, terminators: str = DEFAULT_TERMINATORS) -> list[str]:
    """Split a script turn into sentences (kept in order). Always >=1 unit.

    ``terminators`` is the set of characters that end a sentence; it defaults to
    ASCII ``.!?``. Pass `ELLIPSIS_TERMINATORS` for a gamescript that uses `…`.
    """
    parts = [p.strip() for p in _sentence_re(terminators).split(text) if p.strip()]
    return parts or [text.strip()]


@dataclass
class StoryBind:
    line_id: str
    wav: str
    speaker: str
    subtitle: str            # EXACT in-game subtitle for FW, the ASR transcript for DS2
    gamescript_index: int    # story position (script order)
    quest: str
    score: float
    tier: str                # "1" confident (>=strong), "2" likely (>=accept)
    transcript: str


def match_subtitles(manifest_rows, script_lines, strong=90.0, accept=80.0,
                    min_words=4, terminators=DEFAULT_TERMINATORS):
    """Bind gamescript lines to subtitle-clips (script->clip, token_sort, dedup).

    ``manifest_rows``: dicts with ``line_id``, ``wav``, ``subtitle``,
    ``transcript``. Returns `StoryBind`s for bound lines only, in script order.
    A clip binds at most one script line; a script line takes its single best
    clip if that clip is still free, and yields nothing if it is already taken
    (there is no second-best fallback -- see #392). Score >= ``accept`` binds,
    >= ``strong`` => tier "1". ``min_words`` drops short lines on both sides (a
    2-word bark would match too many script slots). ``terminators`` selects the
    sentence-splitting character set (see `split_sentences`).
    """
    # one matchable unit per script sentence; (index, ordinal) preserves order.
    s_rows = []
    for s in script_lines:
        for ordinal, sent in enumerate(split_sentences(s.text, terminators)):
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
    scored: list[tuple] = []
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
    """`StoryBind`s -> manifest rows for the renderer."""
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
