---
description: "DS splits one spoken speech across several sentence-level lines, so ANY per-line filter (score threshold, length rule, keyword match) punches holes through monologues — selection must operate on passages, and a lone continuation fragment is the audible stub"
type: gotcha
---

Learned 2026-08-05 while curating DS1 deliverable 1. This is the single most important
constraint on filtering DS dialogue and it is invisible until you look at output.

One speech arrives as several catalog rows. Judge each row on its own content — which is
the honest way to judge it — and the middle of a speech scores low because it carries no
content alone:

    "our imagination once gave rise to a rich, vibrant culture"   <- scores high
    "into arable land"                                            <- scores ZERO
    "somewhere along the line we lost sight of tomorrow"          <- scores high

Threshold per line and Heartman's monologue ships with a hole in it. That hole is exactly
the clipped-stub artefact a curated reel exists to remove, so a per-line filter actively
produces the defect it was meant to fix.

## What works

Select **passages**, not points:

1. a line at/above the seed score anchors a keeper;
2. neighbours above a lower fill score join it, so a speech's lead-in and tail come too;
3. short low-score gaps *between two kept lines* are bridged — those are the
   content-free fragments inside one speech.

Real example the bridge saves (`lines_m00060`), where the middle line scored 0:

    Sam:     When I hook up my BB, I see things.
    Deadman: What kind of things?               <- 0, kept by bridging
    Sam:     Like... a face. Someone I don't know. Calling to me.

Without the bridge, Sam answers nobody.

## The inverse hazard

Once runs are never dropped for being short (correct, since there is **no length target**
for this reel), a *lone continuation fragment* can survive as a one-line scene — e.g.
`lines_chiraltower_2019` reduced to the single line "In so doing, they'll carry on the
legacy of the brave souls lost to the tar." That is a stub: grammatically mid-thought,
referring to nothing. A lone line is fine when it is self-contained and striking; it is
a defect when it is a continuation. Check one-line survivors before shipping.

Corollary for agent briefs: tell scorers a downstream span pass keeps speeches whole, so
they score fragments honestly instead of compensating.

Related: [[ds-dialogue-is-variants-not-conversation]], [[ds-keepspans-silently-undertrims]].
