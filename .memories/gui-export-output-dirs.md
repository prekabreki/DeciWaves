---
description: The GUI's rendered-reel output directory is NOT a uniform out/<game>/ — it's out/audio (DS), out/hzd/audio (HZD), out/fw/reels (FW); job_controller.py's own success message is the source of truth
type: reference
---

The GUI's various "where does this game's stuff live under `out/`" helpers are NOT all the
same shape, and it's easy to assume they are:

- **Catalog/config root** (`export_model._out_dir`, `progress_model._out_dir`): DS is
  special-cased to the bare `out/` root (no `out/ds/`); HZD/FW use `out/<game>/`. This
  convention is duplicated identically in both those modules.
- **Rendered `.mp3` reel output** (what actually lands after a successful export) is a
  *third*, unrelated mapping, confirmed via `job_controller.py`'s own post-export success
  message (around line 226): `{"ds": "out/audio", "hzd": "out/hzd/audio", "fw":
  "out/fw/reels"}`. Note DS's reel dir is `out/audio`, NOT the catalog-root convention's bare
  `out/` — the two "DS is special" rules point at different subdirectories.

**Why this matters:** issue #216 (`guide_model.py`, merged then fixed in #220) shipped
`export_done()` checking `out/<game>/` + `out/<game>/reels/` for every game — wrong for DS
*and* HZD, only accidentally right for FW. The bug was baked into the approved plan document
itself (`docs/superpowers/plans/2026-07-21-gui-onboarding-guide-rail.md`, Task 1's own
reference implementation), not introduced by the executor — reviewed and fixed via a
follow-up fold into #220 rather than a bounce, since a bounce would have reproduced the
identical wrong code.

**How to apply:** if you're writing anything that needs to find a game's *rendered reel
output* (not its catalog/config files), grep `job_controller.py` for the authoritative
per-game dir mapping first — don't assume it matches `_out_dir`'s catalog-root convention, and
don't assume all three games share one subdirectory name.
