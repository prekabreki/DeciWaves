"""(A,B) join: structural binds + ASR worklist for ambiguous buckets."""
from __future__ import annotations
from collections import defaultdict

def build_buckets(lines, clips):
    b = defaultdict(lambda: {"lines": [], "clips": []})
    for l in lines:
        b[(int(l["a_bytes"]), int(l["b_samples"]))]["lines"].append(l)
    for c in clips:
        b[(int(c["a_bytes"]), int(c["b_samples"]))]["clips"].append(c)
    return dict(b)

def structural_binds(buckets):
    out = []
    for grp in buckets.values():
        if len(grp["lines"]) == 1 and len(grp["clips"]) == 1:
            out.append((grp["lines"][0]["line_id"], grp["clips"][0]["clip_row"], "S"))
    return out

def relevant_buckets(buckets, keep_line=None):
    """Ambiguous (multi-member) buckets that need ASR + `match.assign_bucket` resolution.

    ``keep_line`` (optional) is a predicate on ``line_id``; when given, a bucket is
    only included if at least one of its candidate lines satisfies it. Used to skip
    pure non-story (ambient/bark) collision buckets that aren't in the manifest.

    Returns whole bucket groups (not a flattened clip worklist) because
    `match.assign_bucket` must resolve a bucket's clips together, as a unit, to do
    unique assignment + elimination.
    """
    out = []
    for grp in buckets.values():
        if not grp["lines"] or (len(grp["lines"]) == 1 and len(grp["clips"]) == 1):
            continue
        if keep_line is not None and not any(keep_line(l["line_id"]) for l in grp["lines"]):
            continue
        out.append(grp)
    return out
