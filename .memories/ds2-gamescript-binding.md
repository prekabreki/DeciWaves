---
description: A BYO DS2 fan gamescript binds roughly half of DS2's clips to a speaker and a story position via ASR + sentence-level fuzzy match -- which unblocks story order and speakers WITHOUT the blocked object reader, provided matching is done per sentence rather than per speaker turn
type: reference
---

Measured 2026-08-01 against a user-supplied local gamescript at
`C:\Users\preka\Documents\deciwaves\ds2\death_stranding_2_gamescript.md` (scraped fan transcript,
BYO, never enters the repo -- see `docs/BYO.md`). Resolves the story-order question left open by
[[ds2-story-order-signals]], and routes around the blocker in [[ds2-types-json]].

## What the gamescript provides

- **2,457 speaker-attributed turns**, `Speaker: text`, in story order.
- **78 distinct speakers** (Sam 578, Dollman 227, Fragile 210, Tarman, Higgs, Heartman, Rainy...).
- An explicit **EPISODE spine**: `PROLOGUE`, `EPISODE 1 - SAM`, `EPISODE 2 - LOU`,
  `EPISODE 3 - DRAWBRIDGE`, `EPISODE 4 - RAINDROPS`, ... -- a ready-made chapter ordering.
- 289 bracketed narration lines (not dialogue; excluded from matching).
- The file is clean UTF-8: it contains **zero** U+FFFD. Apparent mojibake when grepping it on
  Windows is the cp1252 console rendering en-dashes -- see [[windows-python-defaults-to-cp1252]].

## The finding that makes it work: match per SENTENCE, not per turn

The game splits one scripted speaker turn across **several clips**; the gamescript keeps the turn
whole. Matching whole turns therefore fails almost completely -- a first probe scored **1 match in
90 clips** and looked like the gamescript was useless.

Splitting each turn into sentences first (exactly what `games/fw/subtitle_match.split_sentences`
already does, and why it exists) expands 2,457 turns into **10,911 matchable sentences** and
changes the result completely. Same 90 clips, ASR'd (faster-whisper medium, GPU) and matched with
`rapidfuzz.token_sort_ratio` over `engine.text_normalize.normalize`:

| region | n | >=80 | median |
| --- | --- | --- | --- |
| `l100_mex` | 15 | 3 (20%) | 67.1 |
| `l200_aus` | 25 | 11 (44%) | 75.6 |
| `l400_nr1` | 8 | 2 (25%) | 65.8 |
| `l600_nr3` | 8 | 2 (25%) | 64.7 |
| `l700_bea` | 9 | 6 (67%) | 84.8 |
| `(root)` | 25 | 15 (60%) | 90.3 |

**39 of 90 bind at >=80, and most bind at exactly 100.0** with the correct speaker (verified by
eye: Dollman, Fragile, Tarman, The President, Charlie, La Madre). Weighting each region's rate by
its true share of the 8,776 lines gives **~48% overall, i.e. roughly 4,200 clips** carrying a
speaker and a story index.

The unmatched remainder is not failure -- it is ambient/delivery/system chatter ("This cargo has
been designated, keep flat") that a main-story transcript cannot contain by construction. Those
lines still keep the region ordering from [[ds2-story-order-signals]].

## Why this matters architecturally

FW's chain is `extract -> asr -> subtitle-bind -> match -> full-reel -> render`, where
**subtitle-bind is the object-reader-dependent stage**. DS2 has no exact subtitles without that
reader -- but `match_subtitles` binds the *gamescript* to clips, and ASR transcripts can stand in
for the exact-subtitle label. So a DS2 chain of
`extract -> asr -> match(gamescript) -> full-reel -> render` skips the blocked stage entirely.

**RESOLVED 2026-08-02 (#368, shipped).** The open question was what `match_subtitles` should use as
the display label, since it expects rows with both `subtitle` and `transcript` and DS2 has no exact
subtitle. The answer: `games/ds2/story_match.py` sets **`subtitle` to the transcript text** — the
same string lands in both fields — so the matcher runs unmodified and the label is the ASR text.
The chain shipped as `extract -> asr -> match` (no `full-reel`: that stage ships every
*exact-subtitled* line and so depends on the blocked object reader; DS2's renderable set is exactly
its bound lines). `match_subtitles`/`build_rows`/`split_sentences` now live in
`engine/subtitle_match.py`, promoted out of `games/fw/` behind a re-export shim.

**Chain completed 2026-08-02 (#384, shipped):** `extract -> asr -> match -> render`. `render` sits
behind the same BYO-gamescript gate as `match` and defaults to `--tiers 1,2` (DS2 has no tier `S`).
`deciwaves ds2 run` produces the reel *set*; the single story-only MP3 needs an explicit
`deciwaves ds2 render --single-file`.

**The number in this file is still a PREDICTION.** The ~48% came from a 90-clip exploratory harness,
never from the shipped `match` -- and as of 2026-08-02 no `out/ds2/` exists on the dev box, so the
whole chain has produced nothing against the retail install. Reproducing it is **#386**; treat the
bind rate here as a hypothesis until that run replaces these figures with measured ones.

Because `build_rows` emits bound rows only, the unmatched remainder is **dropped from the manifest**,
not ordered -- see [[ds2-story-order-signals]] and **#388**.

## Coverage gap: three story sections are stubs at the source

Measured 2026-08-02 while (re)building the gamescript from its source pages. The EPISODE spine
above is complete as a *spine*, but three of its 18 story sections carry almost no dialogue --
the source publishes them as stubs, verified against the raw HTML so this is not a parser
artifact:

| Section | Spoken lines | Raw content |
|---|---|---|
| `EPISODE 2 - LOU` | 3 | 795 chars |
| `EPISODE 5 - CONFLAGRATION` | 9 | 1,220 chars |
| `EPILOGUE` | 2 | 761 chars |

(`EPISODE 10 - ISOLATION` is thin but real at ~9.5 KB.) The other 14 story sections are
substantial -- Ep 3: 269 lines, Ep 9: 254, Ep 7: 180.

**Consequence for the shipped matcher (#368):** clips belonging to those three
episodes have nothing to match against, so they will fall through to whatever the unmatched path
does. Do not read a low match rate there as a matcher bug -- it is missing input. Closing the gap
needs a second transcript source, not a threshold change.

Conformance of the file as a whole is high: 99.9% of its non-empty lines are recognised by
`games.fw.gamescript.parse` (2,547 dialogue lines, 63 headers, 289 bracketed, only 3 dropped).
