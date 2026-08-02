---
description: A BYO DS2 fan gamescript binds 40.7% of DS2's clips (MEASURED 2026-08-02, #386 -- not the ~48% first predicted) to a speaker and a story position via ASR + sentence-level fuzzy match, unblocking story order and speakers WITHOUT the blocked object reader, provided matching is per sentence not per speaker turn; the shortfall is missing audio in ~7 sections, not a matcher defect
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

## The granularity mismatch runs BOTH ways

1. **One scripted turn -> several clips.** The finding below; why sentence-level matching exists.
2. **One clip -> several scripted sentences.** Confirmed by ear during the #386 spot-check
   (2026-08-02): clips routinely carry more speech than the single sentence they bound to.

(2) has a rate consequence: `match_subtitles` enforces "each clip used once", so when one clip voices
several script sentences, only one of them can ever bind — the rest have their audio *inside an
already-consumed clip* and are structurally unbindable. Not missing audio, not a scoring failure.
This plausibly explains much of the gap between the ~5,270 script sentences that can reach >=80 and
the 3,572 that actually bound. **Attribution stays correct** — 10/10 verified by ear, speaker and
content both right.

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

## MEASURED 2026-08-02 (#386): the real rate is 40.7%, not ~48%

The whole chain ran against the retail install for the first time. **Use these numbers, not the
~48% prediction above** (which came from a 90-clip exploratory harness, never from the shipped
`match`):

| Stage | Result |
|---|---|
| `extract` | `resolved=8776 ok=8757 skipped=12 failed=7` -> 8,769 rows, 3.1 GB WAV (reproduces #360 exactly) |
| `asr` | `ok=8749 err=0` -> 8,769 transcripts, 5 empty, median speech_ratio 0.996 |
| `match` | `joined=8769 script_lines=2547 bound=3572 tier1=3100 tier2=472 quests=59` |

**3,572 / 8,769 = 40.7% bound.** Bind *quality* matched the prediction exactly: **65.9% score
exactly 100.0**, median 100.0, 63 plausible speakers. Story order is clean — `gamescript_index`
monotonic non-decreasing, 59 quest transitions for 59 quests (each section one contiguous block).

### The 7-point shortfall is MISSING AUDIO, not a matcher defect

It is concentrated in ~7 sections that have ample script text but bind ~nothing: `EPISODE 11 -
QUAKE` (109 lines -> 7 clips), `EPISODE 15 - ON THE BEACH` (64 -> 7), `EPISODE 16 - TOMORROW`
(57 -> 3), `EPISODE 13 - DIE HARD` (51 -> 1), `PROLOGUE` (40 -> 4), `THE GOVERNMENT'S BASE - OLD OZ`
(26 -> 1), `ALL RAINY'S QUIZ` (18 -> 0). Together: 384 script lines, 23 clips. At the healthy
~1.5 clips/line they would add ~575 — essentially the entire gap to 48%.

Scoring every script sentence against **all** 8,276 eligible clips with the matcher's own scorer
settles it:

| | sentences | median best score vs ALL clips | reach >=80 |
|---|---|---|---|
| failing sections | 758 | **62** | 11% |
| healthy sections | 10,184 | **81** | 51% |

A median *ceiling* of 62 means no clip in the set voices that text. Ruled out: pre-rendered video
(the install has zero `.bk2`/`.bik`/`.usm`/`.mp4`), and greedy starvation (median clips reachable at
>=80 is **1** in both groups, so a denied sentence rarely had an alternative).

**Lead on where it went:** `streaming_graph.core` indexes 241 files; dialogue resolves to the
per-region `package.01.00.core.stream` voice files and only **7 of 9** yield clips — root 3,358,
`l200_aus` 4,667, `l100_mex` 659, `l700_bea` **37**, `l400_nr1` 23, `l600_nr3` 13, `l500_nr2` 12,
while **`remain` and `l800_fra` yield 0**. `l700_bea` is the Beach, where several unbound endgame
episodes are set, and it gives 37 clips out of a 1.8 GB region. Suggests the dialogue-group
enumeration under-reaches, rather than the content being absent from the install.

**Also found:** `engine/subtitle_match.match_subtitles`' docstring promises "its best *free* clip",
but the code takes `M.argmax(axis=1)` before the greedy pass and skips the sentence entirely when
that one clip is used — no second-best fallback. Low impact here (see the median-1 figure), so it is
a docs/robustness bug, not the cause.

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

**These three stubs are NOT the main coverage gap.** The #386 run (above) found ~7 *other* sections
that fail for the opposite reason -- ample script text, no matching **audio** (Ep 11/13/15/16,
PROLOGUE, OLD OZ, RAINY'S QUIZ). Two distinct failure modes, and the second costs far more clips:
the stubs are missing *text*, those are missing *audio*. Do not conflate them when reading a
per-section rate.

Conformance of the file as a whole is high: 99.9% of its non-empty lines are recognised by
`games.fw.gamescript.parse` (2,547 dialogue lines, 63 headers, 289 bracketed, only 3 dropped).

## Re-run after #391 (2026-08-02, evening) — supersedes the 43.0% figure above

#391 fixed an extract under-reach; the corpus roughly doubled and the chain was re-run end to end.

| stage | result |
| --- | --- |
| `extract` | `resolved=16953 ok=8085 skipped=8769 failed=99` -> **16,854 WAVs** |
| `asr` | `ok=8085 err=0` -> 16,854 transcripts, **2,431 empty** (14.4%, "no active speech") |
| `match` | `bound=4167 tier1=3655 tier2=512 quests=60` (was 3,768 / 3,305 / 463 / 59) |

**Deliverable 1 re-rendered: 4,167 lines, 5:14:45, 264 MB @ 112 kbps** (was 3,768 / 4:44:27).

**Doubling the corpus bought +10.6% story lines, not +90%.** That is the number to remember: clip
count is not the binding constraint. Where the gain landed:

| section | before | after |
| --- | --- | --- |
| EPISODE 15 - ON THE BEACH | 7 | 38 |
| HEARTMAN'S LAB - THE HYDROLOGIST | 15 | 62 |
| THE GOVERNMENT'S BASE - OLD OZ | 1 | 19 |
| EPISODE 11 - QUAKE | 7 | 12 |
| PROLOGUE | 4 | 7 |
| **EPISODE 13 - DIE HARD** | 1 | **1** |
| **ALL RAINY'S QUIZ** | 0 | **0** |

ON THE BEACH was the clean confirmation (`l700_bea` went 37 -> 140 clips). But the **largest
absolute gains were in already-healthy sections** (EPISODE 3 +94, EPISODE 7 +53), i.e. most
recovered audio was ordinary dialogue in well-covered scenes, not the missing scenes.

DIE HARD (51 script lines) and ALL RAINY'S QUIZ (18) did not move at all, so **the missing-audio
hypothesis is exhausted for them** — extraction now reaches ~100% of the game's 16,921 LSSRs. Open
as #400. Do not re-diagnose these as an extract problem.

Baseline kept for diffing at `Documents\deciwaves\out\ds2\story-manifest.prev-391.csv` (3,768 rows).
