---
description: DS2 story order has a real, validated coarse signal that needs no object reader -- the l###_xxx package directory names are numbered story regions (l100_mex early ... l700_bea endgame), confirmed by transcribing clips from each; but 91.5% of lines sit in just two of them, so intra-region group ordering is still unsolved
type: reference
---

Measured 2026-08-01, after story order was made a non-negotiable goal for DS2. Relevant because
Phase 3 (subtitle/speaker binding) is blocked on a DS2 object-reader variant
([[ds2-types-json]]) -- this ordering signal is **independent of that blocker**.

> **Status 2026-08-02: measured but NOT wired into any shipped stage.** `games/ds2/story_match.py`
> writes `build_rows(binds)` -- bound rows only -- so the ~52% of clips that do not match the
> gamescript are dropped from `story-manifest.csv` entirely and get no position at all. That is
> correct for the story-only MP3 (deliverable 1) and **blocks the everything-in-narrative-order reel
> set** (deliverable 2). Wiring this signal in as a fallback tier is **#388**; until that lands,
> nothing in `src/` reads a region. See [[ds2-gamescript-binding]] for the half that did ship.

## The signal: numbered region directories

DS2's package splits stream files across directories whose names are numbered region codes. Every
dialogue clip's `file_index` resolves to exactly one of them, so each of the 8,776 lines gets a
region for free from [[ds2-audio-binding]]'s existing resolver:

| dir | lines | share |
| --- | --- | --- |
| `l100_mex` | 659 | 7.5% |
| `l200_aus` | 4,671 | 53.2% |
| `l400_nr1` | 23 | 0.3% |
| `l500_nr2` | 12 | 0.1% |
| `l600_nr3` | 13 | 0.1% |
| `l700_bea` | 39 | 0.4% |
| `(root)` | 3,359 | 38.3% |

(`l800_fra` holds zero dialogue -- see [[ds2-audio-binding]].)

## It really is story order -- validated by content, not assumed

Six clips sampled evenly by offset from each region, decoded and transcribed (faster-whisper
medium, GPU, all at language probability 1.00):

- **`l100_mex`** -- onboarding/tutorial register: *"It's nice to see you again, Sam... let me just
  confirm order data"*, *"It's a battery-powered vehicle, so if you run out of juice..."*.
- **`l200_aus`** -- the main-map bulk: cargo condition, shelter systems, generic NPC delivery chatter.
- **`l400_nr1`** -- one single group (`g2602`), a self-contained set piece: *"The Odradek is
  reacting to something"*, *"Disperse and look for him!"*.
- **`l600_nr3`** -- a specific named-antagonist mission: *"Forget about Neil, we need to keep
  moving!"*, *"Neil must be on the other side of this train car."*
- **`l700_bea`** -- endgame exposition: *"Only humanity's evolution as a species will cease"*,
  *"we're obviously no match for a monster that size"*.
- **`(root)`** -- mixed system/ambient + story: greetings, cargo-designation lines, *"Let there be water"*.

So the numeric prefix tracks progression (early Mexico → main Australia → numbered `nr` set
pieces → Beach endgame), and the small `nr*`/`bea` dirs are **discrete story missions**, often a
single group. Evidence strength: n=6 per region, judged on register and named story beats -- solid
for a coarse ordering, not a per-line proof.

## What is still unsolved

`l200_aus` + `(root)` = **91.5%** of all lines, and within a region there is no known ordering:

- `group_id` and clip `offset` are **uncorrelated** within the big dirs (r = +0.015 and +0.014),
  so physical layout is not a proxy for anything.
- `group_id` is not monotonic in graph order, and its range overlaps heavily across regions
  (`root` spans 490..76,645), so it is not a global story clock.

What *is* free and exact: **`lssr_index` orders lines within a group**, and a group is one
conversation. So the achievable ordering today is `region → group → lssr_index`, with group
sequence inside a region unknown.

## REFUTED: the sub-group graph carries no progression signal

Probed 2026-08-01 and **falsified** — do not retry it. `Group.sub_group_start/count` index a flat
`sub_groups` table (553,802 entries, sums exactly to the group counts), but it is a *resource
dependency* graph, not a sequence:

- It is **not even acyclic**: a Kahn topological sort orders only 58,072 of 79,317 groups,
  leaving **21,245 in cycles**.
- Correlation between topological rank and the content-validated region rank above is
  **-0.028** — no signal at all (n = 4,418 lines).
- Only **292 of the 744** dialogue groups have any parent, so 61% are unreachable from it anyway.
- Parents are not scene/quest containers: the top shared parents mix regions freely
  (e.g. one parent's dialogue children span `(root)` 10, `l200_aus` 3, `l100_mex` 1), and one
  group is referenced by 7,009 parents — a shared bundle, not a story node.

## The useful thing that probe DID establish

All 8,776 lines live in just **744 groups** (~12 lines each), and a group is one conversation with
exact internal order via `lssr_index`. So the open problem is not "order 8,776 lines" but
**"order 744 conversations"**, already partitioned into content-validated regions. That is small
enough for a transcript/synopsis-anchored pass (ASR the clips, match conversations to story beats)
rather than requiring the object reader.

The remaining known-good route is still the DS/FW one: anchor against a BYO
gamescript/transcript (`games/ds/story_order.py` falls back to numeric scene order from names;
DS2 has no names without the object reader).
