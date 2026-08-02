---
description: "DS render without --speech-trim adds ~51 minutes of pure dead air (measured); the keep-spans map is BUNDLED in the repo, and the DS workspace's other intermediates are regenerable/packaged too"
type: gotcha
---

Measured 2026-08-02 on the real install, rendering the same line set twice.

| | duration | segments |
|---|---|---|
| with `--speech-trim` | 5:41:54 | 2,049 |
| without | **6:18:01** | 1,846 (a strictly *smaller* set) |

**+51 minutes of pure dead air from one omitted flag**, on a line set that was 203 rows shorter.
DS cutscene audio is whole-scene Wwise tracks, so without the keep-spans map each cutscene plays
at full length including all the non-speech gameplay audio between its lines. The render prints
a clean success and a plausible duration — nothing warns. This is the single largest silent
quality regression available in the DS pipeline.

`--speech-trim` defaults to `""` (disabled) in `games/ds/render.py`. See #408.

## What is bundled vs what the workspace needs

`src/deciwaves/data/ds/` **ships three pre-resolved artifacts**, so none of them needs
regenerating against a user install (and `ds trim` needs a GPU, so this matters):

- `cutscene-keepspans.csv` (34 KB, 109 tracks)
- `cutscene_tracks.csv`
- `data-file-list.txt`

`deciwaves ds run` resolves the keep-spans itself (`cli/run.py::_ds_render_argv`, via
`data.packaged(...)`) and deliberately omits the `cutscenes` stage for the same reason. **`ds run`
is correct**; only a direct `deciwaves ds render` call is exposed.

**Inconsistent default worth knowing:** `games/ds/catalog.py` defaults its file list to the
*packaged* `ds/data-file-list.txt`, but `games/ds/cutscene_audio.py` defaults `--file-list` to
`out/data-file-list.txt` — a workspace path nothing in the pipeline writes. So
`deciwaves ds cutscenes` fails out of the box with a bare `[Errno 2]` on a file the repo
actually ships. Pass `--file-list src/deciwaves/data/ds/data-file-list.txt`.

## Diagnosing this after the fact

`out/wav-cache/kept/` is written only by `apply_keep_spans`. If it holds ~109 files, a previous
render used the trim; if a later reel is much longer than an older one over the same or fewer
lines, the flag was dropped. Gap accounting is NOT the explanation — check it and rule it out
(scene vs line gaps moved only 1.4 min across the same comparison).

Related: [[ds1-story-reel-composition]], [[ds-render-honours-playlist-order]].
