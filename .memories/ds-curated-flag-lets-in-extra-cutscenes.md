---
description: "`ds render --curated` bypasses NON_STORY_CS_GROUPS by design, so Extra/Battlefield cutscene groups flow into a 'story' cut and can even END it — an external curator must drop them itself, and must read the group set from episode_map rather than listing groups by hand"
type: gotcha
---

Learned 2026-08-05. `--curated` (#406) exists so an external playlist's membership and
order are authoritative: it neutralises the `is_side` / `main_story_only` filters. That is
correct and wanted — but it also switches off the **non-story cutscene** cull, which is the
one filter a story cut still needs.

`games/ds/episode_map.NON_STORY_CS_GROUPS` is derived (`"Extra" in title or "Battlefield"
in title`) and as of 2026-08-05 is:

    cs50, cs56, cs71, cs77, cs80

In the DS1 curated playlist that was **47 cutscene tracks** of Ludens-Fan / Battlefield /
Fragile-teleport material. Two specific harms:

- `sq_cs71_s00270` is the **same ~2.4 s line on 16 separate tracks** — 38 s of repetition.
- cs50 sorts *after* cs10, so the reel **ended on Extra content** instead of on cs10
  ("The Last Stranding"), the actual finale.

**Read the set from the repo, do not hand-pick it.** Eyeballing the playlist gave
`("cs71","cs77","cs80")` — it missed cs50 precisely because cs50's harm (ending the reel)
was invisible in a group-frequency listing. Import `NON_STORY_CS_GROUPS`.

Two related facts worth not re-deriving:

- **`cs11` is not missing.** "Finale & Epilogue" exists in `CS_TITLES` but the catalog holds
  only `sq_cs11_s00100` with two title-card lines ("EPISODE 15 …", "Two Weeks Earlier") and
  no audio. The finale's dialogue is in **cs10**. An absent cs11 is not a bug.
- **`cs53` is real main story** and deliberately absent from the non-story set; its
  `CS_ORDER_HINT` of 3.5 correctly lands it between cs03 and cs04.

Related: [[ds-render-honours-playlist-order]], [[ds1-story-reel-composition]].
