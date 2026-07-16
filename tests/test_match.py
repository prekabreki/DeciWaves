from deciwaves.games.hzd.match import assign_bucket

C = [{"line_id": "L1", "subtitle_en": "I'll find a way to stop it."},
     {"line_id": "L2", "subtitle_en": "We should head north now."}]

def test_tier1_unique_strong():
    out = assign_bucket(C, ["c1"], {"c1": "ill find a way to stop it"})
    assert out["c1"][0] == "L1" and out["c1"][1] == "1"

def test_tier3_no_match():
    out = assign_bucket(C, ["c1"], {"c1": "completely unrelated words here"})
    assert out["c1"] == (None, "3", 0.0)

def test_tier2_close_runners():
    # token_set_ratio: "open the gate" vs "open the gate"=100, vs "open the door"=76.19
    # gap=23.81, so margin=30 puts the runner-up inside the margin → tier "2"
    close = [{"line_id": "A", "subtitle_en": "open the gate"},
             {"line_id": "B", "subtitle_en": "open the door"}]
    out = assign_bucket(close, ["c1"], {"c1": "open the gate"}, margin=30)
    assert out["c1"][1] == "2"          # runner-up within explicit margin → downgraded


def test_tier1_at_default_margin():
    # At default margin=8.0, gap=23.81 > 8.0 → confident tier-1 match
    close = [{"line_id": "A", "subtitle_en": "open the gate"},
             {"line_id": "B", "subtitle_en": "open the door"}]
    out = assign_bucket(close, ["c1"], {"c1": "open the gate"})
    assert out["c1"][1] == "1" and out["c1"][0] == "A"


def test_long_transcript_not_bound_to_short_subset_subtitle():
    """token_set_ratio returns 100 when a short candidate subtitle is a subset of a
    long transcript ('Aloy!' is a token subset of a longer full-sentence line spoken to
    her), which can mis-bind a clip to the wrong short shout line. The fix must bind to
    the real length-matching line instead."""
    cands = [{"line_id": "ALOY", "subtitle_en": "Aloy!"},
             {"line_id": "SYLENS", "subtitle_en": "Aloy, follow my lead or the plan is ruined."}]
    out = assign_bucket(cands, ["c1"], {"c1": "Aloy, follow my lead or the plan is ruined"})
    assert out["c1"][0] == "SYLENS"


def test_guard_preserves_legitimate_short_match():
    """The short-subtitle guard must not break a genuine short clip<->short line match."""
    cands = [{"line_id": "ALOY", "subtitle_en": "Aloy!"},
             {"line_id": "OTHER", "subtitle_en": "We should head north now."}]
    out = assign_bucket(cands, ["c1"], {"c1": "Aloy!"})
    assert out["c1"][0] == "ALOY"


def test_short_transcript_not_bound_to_long_subset_subtitle():
    """Reverse subset: a short transcript ('Aloy!') must not match a long subtitle that
    merely contains it as a token subset; it should bind to the short shout line instead."""
    cands = [{"line_id": "SYLENS", "subtitle_en": "Aloy! Follow my lead, or the plan is ruined!"},
             {"line_id": "ALOY", "subtitle_en": "ALOY!!!"}]
    out = assign_bucket(cands, ["c1"], {"c1": "Aloy!"})
    assert out["c1"][0] == "ALOY"


def test_assign_bucket_unique_and_elimination():
    """Confident clips claim their lines uniquely; the last leftover clip+line pair by
    elimination (tier 'E') even when ASR mangled the clip's transcript."""
    lines = [{"line_id": "L1", "subtitle_en": "open the gate"},
             {"line_id": "L2", "subtitle_en": "close the door slowly"},
             {"line_id": "ALOY", "subtitle_en": "ALOY!!!"}]
    transcripts = {"c1": "open the gate", "c2": "close the door slowly", "c3": "Eli!"}
    out = assign_bucket(lines, ["c1", "c2", "c3"], transcripts)
    assert out["c1"][0] == "L1"
    assert out["c2"][0] == "L2"
    assert out["c3"][0] == "ALOY" and out["c3"][1] == "E"   # mangled clip recovered by elimination


def test_assign_bucket_greedy_leftover_pairing():
    """Multiple leftovers (ASR-mangled in an exact-(A,B) bucket) pair greedily by best
    score, strongest signal first, remainder by exclusion -- all tier 'E'."""
    lines = [{"line_id": "NORA", "subtitle_en": "Nora! Make way for Aloy!"},
             {"line_id": "ALOY", "subtitle_en": "ALOY!!!"}]
    transcripts = {"c1": "Nora! Make way for Eli!", "c2": "Eli!"}   # ASR heard 'Eli' for 'Aloy'
    out = assign_bucket(lines, ["c1", "c2"], transcripts)
    assert out["c1"] == ("NORA", "E", out["c1"][2])   # stronger partial match claims NORA
    assert out["c2"][0] == "ALOY" and out["c2"][1] == "E"   # remainder by exclusion


def test_assign_bucket_no_double_assignment():
    """Two clips matching the same line: only one wins; the other doesn't steal the line."""
    lines = [{"line_id": "L1", "subtitle_en": "open the gate"},
             {"line_id": "L2", "subtitle_en": "head north to the ridge"}]
    transcripts = {"c1": "open the gate", "c2": "open the gate"}   # both match L1
    out = assign_bucket(lines, ["c1", "c2"], transcripts)
    assigned = [v[0] for v in out.values() if v[0]]
    assert assigned.count("L1") == 1          # L1 claimed once, not twice


def test_assign_bucket_partial_bucket_skips_elimination():
    """Partial bucket (a clip was capped/dropped upstream): with fewer clips than lines the
    'remaining clips ARE the remaining lines' assumption is false. Elimination must NOT
    force-bind a surviving clip to a line whose real clip is absent. The mangled
    survivor is left unbound rather than fabricating a confident-looking bind."""
    lines = [{"line_id": "L1", "subtitle_en": "open the gate"},
             {"line_id": "L2", "subtitle_en": "close the door slowly"}]
    transcripts = {"c2": "Eli!"}              # matches NEITHER line strongly; c1 was capped out
    out = assign_bucket(lines, ["c2"], transcripts)
    assert out["c2"] == (None, "3", 0.0)      # left unbound, not paired by (false) exclusion


def test_assign_bucket_consolation_assignment_is_never_tier1():
    """The tier margin must be judged against the ASSIGNED line, not the clip's own
    top-2 gap. Clip A is the clear (100) top match for LX, claiming it first. Clip B's
    OWN top choice is also LX (92.86) -- already taken -- so B is a consolation
    assignment to LY (80.77), its second choice. B's own top-2 gap (92.86-80.77=12.09)
    clears the default margin, so the old code (which measured the gap against
    `ranked[0]`/`ranked[1]` regardless of which line was actually assigned) called this
    tier '1'. Since LY isn't B's top-ranked line, it must be tier '2'."""
    lines = [{"line_id": "LX", "subtitle_en": "bring the supplies to the camp now"},
             {"line_id": "LY", "subtitle_en": "bring the supplies to the outpost now"}]
    transcripts = {"A": "bring the supplies to the camp now",
                   "B": "bring the supplies to the camp soon"}
    out = assign_bucket(lines, ["A", "B"], transcripts, strong=75.0)
    assert out["A"] == ("LX", "1", 100.0)               # clear top match, tier 1 stands
    assert out["B"][0] == "LY"                          # consolation assignment
    assert out["B"][1] == "2"                           # must NOT be tier 1


def test_assign_bucket_partial_bucket_still_binds_confident():
    """The partial-bucket guard suppresses only by-exclusion pairing, not genuine matches:
    a strong unique match is still bound even when clips < lines."""
    lines = [{"line_id": "L1", "subtitle_en": "open the gate"},
             {"line_id": "L2", "subtitle_en": "close the door slowly"}]
    transcripts = {"c1": "open the gate"}     # strong, unique match to L1
    out = assign_bucket(lines, ["c1"], transcripts)
    assert out["c1"][0] == "L1" and out["c1"][1] in ("1", "2")
