---
description: "`ds render` renders playlist.csv rows verbatim in file order — but ONLY on the --single-file path; the multi-reel path packs WHOLE EPISODES in ascending order and silently undoes any cross-episode reordering"
type: architecture
---

> **CORRECTION 2026-08-05 — read this before trusting the 'no sort' claim below.**
> Fact 2 ("render.py preserves that order; nothing downstream re-sorts") holds for
> `--single-file`. It is **false for the multi-reel path**: `finish_render` →
> `engine/render.py:pack_episodes` groups **whole episodes in ascending `episode`
> order**, so playlist order is honoured only *within* one episode.
>
> This cost a full render. A curated playlist that interleaved 53 prepper-interview
> blocks through the story spine came back re-stratified — reel 00 hour 4 was
> 926/928 `terminal` — because every row was regrouped under its own story episode.
> It also explains why the un-woven reel looked stratified in the first place: **the
> stratification is imposed at render time, not present in the playlist.**
>
> Workaround that works: renumber `episode` so it encodes the desired block order
> (one episode per contiguous block, monotonic). Episode-sorting then preserves the
> arrangement. The cost is that the tracklist's `episode` column becomes a block
> index rather than a story episode; the story episode stays recoverable from `scene`.
>
> Verify order survived a render by comparing playlist `line_id` order against the
> concatenated tracklists — do not assume it.

Measured 2026-08-02 while designing the externally-curated deliverable-1 workflow. The question
was "how much repo work does DS need to accept a curated line selection/ordering?" The answer is
**almost none**, which was not obvious and is worth not re-deriving.

Three facts, all in `games/ds/`:

1. **`story_order.read_playlist()` (story_order.py:209) reads rows in file order and does not
   sort.** It just builds a `Segment` per CSV row and returns the list.
2. **`render.py` preserves that order.** Its `--main-story` / `--single-file` branches filter
   with `main_story_only()`, which is order-preserving; nothing downstream re-sorts.
3. **`gap_key=lambda s: s.scene`** (render.py:217, 253, 284) — so a scene change already gets
   `SCENE_GAP` (1.5 s) and lines within a scene get `LINE_GAP` (0.4 s). Reordering rows so that
   one scene is contiguous automatically produces correct gap placement.

So a curated `playlist.csv` — same 12 columns, rows dropped and reordered — renders verbatim.
**No manifest adapter, no new stage, no `build_spine` port is needed for DS.** (DS is the one
game that does *not* use `engine/render_spine.build_spine`; ds2/fw/hzd all do. That asymmetry
turned out not to matter.)

**The one real obstruction:** `--single-file` and `--main-story` call `main_story_only()`
*unconditionally*, re-filtering by `is_side` and `episode_map.NON_STORY_CS_GROUPS`. On a curated
playlist that silently discards deliberately-kept non-story material. Fixed by the `--curated`
flag in #406.

Related: [[ds1-story-reel-composition]].
