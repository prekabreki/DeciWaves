---
description: "Measured composition of the DS1 --main-story reel: 60% of runtime is cutscene, 40% is main-cast codec calls, and ~8% is subtitled system/ambient pollution the subtitle_en filter cannot catch"
type: measurement
---

Measured 2026-08-02 from the real artifact (`out/audio/phase_d_main_00.tracklist.csv`, rendered
2026-07-18 — i.e. *after* the ordering fixes `ca255ae`/`e501868`, so this is the honest quality of
the current heuristic, not a known bug).

## By runtime, not row count

The row/runtime split is wildly different because DS cutscenes are whole-scene Wwise tracks
(~108 s each) while `mission` lines are individual utterances (~3.9 s each). Counting rows badly
misleads here.

| category | rows | runtime | share | avg |
|---|---|---|---|---|
| `cutscene` | 107 | 3.20 h | **60.2%** | 108 s |
| `mission` | 1,939 | 2.12 h | 39.8% | 3.9 s |

Total ~5.32 h, 13 episodes (0-11 then a jump to 15; 12-14 absent).

Top `mission` speakers: Die-Hardman 989, Mama 313, Deadman 293, Heartman 128, Sam 120,
Fragile 41. **The `mission` category is largely the main cast's codec calls** — so the reel is
already roughly 60% cutscene story / 40% codec, close to the desired shape.

## The ~8% pollution, and why no rule removes it

`games/ds/selection.py` rule 1 (require non-empty `subtitle_en`) is a genuinely principled bark
filter — only 44.3% of the 26,452 catalog lines have a subtitle, and a line with no subtitle is a
bark by the game's own construction. **But it only catches *unsubtitled* barks.** DS1's subtitled
system and ambient lines pass straight through. The reel literally opens with:

- Operator: "Warning. Not all required cargo present for processing." (UI announcement)
- Operator: "You may select 'Partial Delivery' to submit required cargo..." (UI instruction)
- Sam: "It's too damn steep." / "No getting up this." (traversal barks)
- Deadman: "Might want to check your compass if you are." (navigation hint)

Sam has 120 such `mission` lines; there is also a "Bomb Announcement" speaker. These are
structurally *identical* to real story lines — same category, same speaker set, subtitle present.
**Only meaning separates them**, which is why selection moved to an external editorial pass
(#406/#407) rather than a better rule.

## Ordering shape

Episodes are cleanly sequential, but *within* an episode the 3.9 s mission lines and 108 s
cutscene tracks interleave across 27 contiguous runs. Short codec fragments landing beside a
two-minute scene, not chronologically placed against it, is the likely source of the perceived
"weird shuffling".

The useful granularity for fixing it is **`scene` (249 distinct values in the playlist), not
line** — within-scene `line_index` order is the game's own and is correct by construction.

Related: [[ds-render-honours-playlist-order]].
