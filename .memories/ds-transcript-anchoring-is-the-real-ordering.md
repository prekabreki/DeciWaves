---
description: "DS's default playlist order is the UN-anchored fallback; `ds order --transcript <gamescript>` is the real ordering and fixes the opening, but low-text scenes anchor unreliably within a cutscene group"
type: gotcha
---

`games/ds/story_order.py` supports transcript anchoring via `games/ds/transcript_anchor.py`,
which matches ~93% of distinctive cutscene subtitles against a BYO gamescript and uses each
scene's **median matched position** as a narrative anchor. It then orders cutscene *groups* by
their median anchor and assigns non-cutscene scenes to the nearest anchored group.

**But `--transcript` defaults to `""` (disabled), so the playlist everyone actually has is the
un-anchored `episode_map` fallback.** That is not a small difference.

## What anchoring fixes (measured 2026-08-02, DS:DC + a 4,328-line fan gamescript)

Un-anchored, the DS1 story reel opens on **`lines_m00010` — Operator UI announcements**
("Warning. Not all required cargo present for processing.") and Sam traversal barks. The game's
prologue sits hundreds of lines later.

Anchored, it opens on **`sq_cs00_s00100`** — the rope/stick narration, i.e. the actual opening
of the game — and (after curation drops `m00010`, which is entirely Operator/Sam pollution)
continues into `sq_cs00_s00220`, the Sam/Fragile cave meeting.

Interleaving also improves: contiguous category runs go **30 -> 35** over the same 2,104 story
rows. The longest mission run (441 lines, ~29 min of consecutive briefings) is **unchanged** —
anchoring does not break that up.

## The limitation: low-text scenes drift within a group — FIXED in #413 (2026-08-05)

The anchor is a text match, so a scene with little distinctive dialogue got a weak or absent
anchor and landed in the wrong place *within* its cutscene group. Observed for `cs00`:

    anchored order: s00100, s00220, s00300, s00110, s00200, s00600, s00400, s00450
    natural order:  s00100, s00110, s00200, s00220, s00300, s00400, s00450, s00600

`s00110` is Sam's crash (mostly non-verbal) and `s00200` is a one-line title card
(`PROLOGUE "PORTER"`) — exactly the two with nothing to match on.

**There were two defects here, and the second is the one you actually hear.** An *unanchored*
cutscene scene used to take a synthetic position `group_pos + s_number * 1e-3`. With s-numbers
running to `s03600` that band is several units wide — fake precision. Any mission or terminal
scene whose own anchor landed inside it sorted into the middle of a continuous cinematic. That
is what put a Deadman codec call 54 s into the DS1 reel, inside the opening prologue.

`build_playlist` now re-deals a group's anchored positions to its scenes in s-number order, and
glues an unanchored scene to its predecessor (`_CS_GLUE = 1e-6`) instead of letting it claim a
slot. Measured old-vs-new on the real install with identical inputs: group order **identical**
(cs53 still between cs03/cs04), within-group inversions **101 → 9** (all 9 in `cs71`, a
non-story Extra), 6,588 segments both sides, and total interleaved lines unchanged at 1,807 —
the fix closes the fake gaps without collapsing cutscene groups into one block, so the pacing
the weave depends on survives.

**Anchor noise is only visible within a group, never between groups.** Group order comes from a
*median* over the group's scenes, which averages the noise away; per-scene positions have no
such smoothing. Trust the anchor at group granularity, distrust it below that.

## Invocation

```
deciwaves ds order --catalog out/catalog.csv \
  --cutscene-tracks src/deciwaves/data/ds/cutscene_tracks.csv \
  --transcript <gamescript.md> --out <playlist.csv>
```

The gamescript is BYO and never committed. On this machine all four games' scripts live in
`Documents\deciwaves\{ds1,ds2,fw,hzd}`.

Related: [[ds1-story-reel-composition]], [[ds-render-honours-playlist-order]],
[[ds-speech-trim-is-load-bearing]].
