"""Transcript -> candidate-subtitle matching with tiered confidence."""
from __future__ import annotations
import re
from dataclasses import dataclass
from rapidfuzz import fuzz

@dataclass
class Match:
    line_id: str | None
    score: float
    tier: str

_MARKUP = re.compile(r"<[^>]*>")        # HZD subtitle directives: <subtitle-delay=..>, <split..>
_PUNCT = re.compile(r"[^\w\s]")
def normalize(s):
    s = _MARKUP.sub(" ", s)             # drop markup before punctuation (not spoken)
    return re.sub(r"\s+", " ", _PUNCT.sub("", s.lower())).strip()


def _score(t, sub):
    """Similarity of a normalized transcript ``t`` to a normalized subtitle ``sub``.

    token_set_ratio is forgiving of ASR word add/drop/reorder, but it returns 100 when one
    string's tokens are merely a SUBSET of the other -- in EITHER direction: a short subtitle
    inside a long transcript ("aloy" ⊂ "aloy do as i say...") mis-bound a Sylens clip to the
    prologue "ALOY!!!"; and a short transcript inside a long subtitle pulled Rost's shouted
    "Aloy!" toward that same Sylens line. When the lengths differ a lot, fall back to the
    order-sensitive token_sort_ratio (doesn't collapse subsets). Near-equal lengths (incl.
    ASR filler/misspellings) keep the lenient token_set_ratio.
    """
    base = fuzz.token_set_ratio(t, sub)
    sw, tw = len(sub.split()), len(t.split())
    if max(sw, tw) > 2 * max(1, min(sw, tw)):
        return min(base, fuzz.token_sort_ratio(t, sub))
    return base


def assign_bucket(lines, clip_rows, transcripts, strong=90.0, margin=8.0):
    """Resolve one (A,B) bucket: assign clips to lines uniquely, then fill by elimination.

    ``lines``: candidate line dicts (line_id, subtitle_en). ``clip_rows``: the bucket's clip
    ids. ``transcripts``: {clip_row: text}. Returns {clip_row: (line_id|None, tier, score)}:
      * confident unique matches (score >= strong), greedily by score -> tier "1"/"2";
      * if exactly ONE line and ONE clip remain after that, pair them -> tier "E" (inferred
        by exclusion -- recovers clips whose shouted/one-word audio ASR mangled);
      * everything else -> tier "3" (unbound). Each line and each clip is used at most once.
    """
    norm = [(l["line_id"], normalize(l["subtitle_en"])) for l in lines]
    by_clip = {}
    for cr in clip_rows:
        t = normalize(transcripts.get(cr, ""))
        by_clip[cr] = sorted(((_score(t, sub), lid) for lid, sub in norm),
                             key=lambda x: x[0], reverse=True)
    triples = sorted(((s, cr, lid) for cr in clip_rows for s, lid in by_clip[cr]),
                     key=lambda x: x[0], reverse=True)
    result = {cr: (None, "3", 0.0) for cr in clip_rows}
    used_c, used_l = set(), set()
    for s, cr, lid in triples:
        if s < strong or cr in used_c or lid in used_l:
            continue
        ranked = by_clip[cr]
        runner = ranked[1][0] if len(ranked) > 1 else 0.0
        generic = len(normalize(transcripts.get(cr, "")).split()) <= 2
        tier = "2" if (ranked[0][0] - runner < margin or generic) else "1"
        result[cr] = (lid, tier, s)
        used_c.add(cr); used_l.add(lid)
    # Leftover pairing: in an exact-(A,B) bucket the remaining clips ARE the remaining lines,
    # just mangled by ASR (shouts, names, markup). Pair greedily by best score (strongest
    # signal first, remainder by exclusion) as tier "E" (inferred, lower confidence).
    #
    # This "by exclusion" inference is only sound when the bucket is whole: with fewer clips
    # than lines (e.g. a clip was capped/dropped upstream) a surviving mangled clip would
    # be force-bound to a line whose real clip is simply absent -- a fabricated bind. When the
    # bucket is partial, skip elimination and leave the survivors unbound (tier "3").
    if len(clip_rows) < len(lines):
        return result
    sub_of = dict(norm)
    left_c = [cr for cr in clip_rows if cr not in used_c]
    left_l = [lid for lid, _ in norm if lid not in used_l]
    lpairs = sorted(((_score(normalize(transcripts.get(cr, "")), sub_of[lid]), cr, lid)
                     for cr in left_c for lid in left_l), key=lambda x: x[0], reverse=True)
    for s, cr, lid in lpairs:
        if cr in used_c or lid in used_l:
            continue
        result[cr] = (lid, "E", s)
        used_c.add(cr); used_l.add(lid)
    return result


def match_clip(transcript, candidates, speech_ratio, strong=90.0, margin=8.0):
    # strong/margin are starting-point thresholds; tune against the validation
    # sample before shipping (spec §calibration defers this to real data).
    t = normalize(transcript)
    scored = sorted(
        ((_score(t, normalize(c["subtitle_en"])), c) for c in candidates),
        key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < strong:
        return Match(None, scored[0][0] if scored else 0.0, "3")
    top_score, top = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    generic = len(t.split()) <= 2
    tier = "2" if (top_score - runner < margin or generic or speech_ratio < 0.5) else "1"
    return Match(top["line_id"], top_score, tier)
