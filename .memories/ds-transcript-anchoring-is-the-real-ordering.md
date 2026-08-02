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

## The limitation: low-text scenes drift within a group

The anchor is a text match, so a scene with little distinctive dialogue gets a weak or absent
anchor and lands in the wrong place *within* its cutscene group. Observed for `cs00`:

    anchored order: s00100, s00220, s00300, s00110, s00200, s00600, s00400, s00450
    natural order:  s00100, s00110, s00200, s00220, s00300, s00400, s00450, s00600

`s00110` is Sam's crash (mostly non-verbal) and `s00200` is a one-line title card
(`PROLOGUE "PORTER"`) — exactly the two with nothing to match on.

**Likely refinement (untested):** order cutscene *groups* by anchor, but keep the natural
`s`-number order *within* a group. The s-number is the game's own sequence and should probably
never be overridden by a weak text match. `story_order.build_playlist` currently sorts scenes by
their individual anchors, not just groups.

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
