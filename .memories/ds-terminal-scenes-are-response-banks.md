---
description: "A DS `terminal` scene is a state-keyed BANK of per-delivery response variants, not a conversation — played in line_index order it repeats itself and plays both mutually exclusive endings"
type: format-finding
---

Every DS prepper facility is **one scene** holding **every response the game can pick from**,
selected at runtime by game state (pre-contract / mid-delivery / post-delivery / after they
join or refuse). Nothing in the catalog records that state, so a reel that plays the scene
end-to-end in `line_index` order — which is what `story_order` emits and what
`ds render --curated` renders — produces something no player ever hears.

Measured on `lines_pr202` (The Elder, 107 lines after the standard bark/tutorial drops):

- **Both mutually exclusive endings play.** He joins the UCA at `line_index` 42 and again at
  164, and refuses it at 83 and again at 175. In game these are different playthroughs.
- **The same content recurs two or three times**, and the repeats do not collide on an exact
  match, so `selection.filter_and_dedup` lets them through (see #419):
  - *encoding variants* — li 29 `It<mojibake>s a miracle it made it this far.` vs li 72
    `It's a miracle it made it this far.` differ only in the apostrophe byte;
  - *re-splits across sentence boundaries* — "We can't make it on our own." + "I think I knew
    that deep down…but it took you to make me admit it." in one place, and "We can't make it
    on our own. Think I knew that deep down…" + "But it took you to make me admit it." in
    another. **Neither half clears a pairwise similarity ratio.** Catch these by measuring how
    much of a candidate line already appears *anywhere* in what that scene has said so far,
    not line-against-line.
- **Roughly 4% is transactional chatter** — cargo checks ("Let's see how's the package…",
  "How much cargo we talking here…?"), greetings, delivery grading ("Not bad.") — the same
  class of material as the `npc` bark banks.

Across all 39 terminal scenes in the DS1 cut this was 147 lines of 3,103 (dedupe 17, filler
126, losing-branch 4). Verified: all 39 scenes are emitted in strict `line_index` order.

**Consequence for any DS reel.** `terminal` is the largest category in a woven DS1 cut (~50%
of segments) and it is the *prize* — 43 facilities of prepper interviews. It cannot simply be
played in file order. It needs, per facility: dedupe (normalized + coverage-based) → drop the
transactional filler → pick ONE branch → put the resolution monologue last.

The engine half of that (the dedupe) is #419. The branch-picking is judgement and lives in the
out-of-repo curation scripts per the agreed seam.

**Whatever rule you write, audit the DISCARD pile, not the keep pile.** A first pass here ate
"I'm impressed, Sam. You've brought pretty much the entire region together" (a real
acknowledgement, caught by a bare `^i'm impressed`) and "let's see how she's doing" (the Doctor
examining a patient, caught by a cargo-check pattern). The keep pile looked fine both times.

Related: [[ds-transcript-anchoring-is-the-real-ordering]], [[ds1-story-reel-composition]].
