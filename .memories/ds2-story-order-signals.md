---
description: DS2 story order has a real, validated coarse signal that needs no object reader -- the l###_xxx package directory names are numbered story regions (l100_mex early ... l700_bea endgame), confirmed by transcribing clips from each; but 91.5% of lines sit in just two of them, so intra-region group ordering is still unsolved
type: reference
---

Measured 2026-08-01, after story order was made a non-negotiable goal for DS2. Relevant because
Phase 3 (subtitle/speaker binding) is blocked on a DS2 object-reader variant
([[ds2-types-json]]) -- this ordering signal is **independent of that blocker**.

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

Untested leads for intra-region group order: the graph's `sub_group_start/count` DAG
(a topological/load order), and the DS/FW approach of anchoring against a BYO
gamescript/transcript (`games/ds/story_order.py` falls back to numeric scene order from names;
DS2 has no names without the object reader).
