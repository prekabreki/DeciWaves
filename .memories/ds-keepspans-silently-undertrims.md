---
description: "ds/cutscene-keepspans.csv is WhisperX ASR output consumed blind by the renderer, so where ASR under-detects speech the render silently trims real dialogue away — 6 DS1 scenes lose ~12 min including the game's opening narration, with no error anywhere"
type: gotcha
---

Found 2026-08-05 by measuring the rendered DS1 story cut, not by reading code.

`games/ds/cutscene_trim.py` transcribes each whole-scene cutscene track with WhisperX and
writes `speech_ratio` + `keep_spans` to `src/deciwaves/data/ds/cutscene-keepspans.csv`.
`games/ds/render.py:load_keepspans` consumes it with **no sanity check**, so an ASR miss
becomes silently discarded dialogue. Nothing appears in `render-errors*.log` (0 bytes) and
the reel looks fine.

Trimming itself is load-bearing and must stay — see [[ds-speech-trim-is-load-bearing]]
(omitting it costs ~51 min of dead air). The problem is unvalidated trim data.

## The cheap oracle

Compare each scene's kept span duration against `subtitle_words / 2.4` (a deliberate
under-estimate of delivery). Three things must be right or it false-positives:

- **dedupe subtitle text per scene** and drop `<ignoresub>` rows (both occur in
  `sq_cs00_s00100`);
- **sum all tracks of a scene** before comparing — a cutscene scene can render as several
  tracks (alternate takes: `sq_cs09_s00440` has 3, `sq_cs00_s00400` has 3 at 4.3 s /
  83.2 s / 20.7 s). Per-track comparison flags healthy scenes as broken;
- healthy scenes score `speech_ratio` **0.76–0.89**.

## The six DS1 scenes, and the two distinct causes

ASR under-detection (low ratio — regenerating keepspans should recover these):

| scene | ratio | kept | needs |
|---|---|---|---|
| `sq_cs00_s00100` | 0.132 | 24.7 s | ~40 s — **the rope/stick opening narration** |
| `sq_cs03_s01300` | 0.212 | 21.5 s | ~237 s |

Source shorter than its subtitles (healthy ratio, so trim is NOT the cause — the track
does not contain the audio; do **not** "fix" by padding spans, that fabricates audio):

| scene | ratio | kept | short by |
|---|---|---|---|
| `sq_cs08_s00100` | 0.840 | 141.7 s | −251 s |
| `sq_cs06_s00350` | 0.886 | 169.9 s | −170 s |
| `sq_cs08_s01300` | 0.761 | 285.1 s | −35 s |
| `sq_cs07_s00700` | 0.774 | 74.3 s | −11 s |

`sq_cs03_s01300` is ambiguous: its full untrimmed track is only ~101 s (21.5 / 0.212)
against ~237 s of subtitles, so even disabling trim does not rescue it — it may belong in
the second group. A live alternative hypothesis for group two is that the catalog holds
alternate takes, inflating the word count.

Related: [[ds-speech-trim-is-load-bearing]], [[ds-cutscene-audio]],
[[ds-speech-spans-multiple-lines]].
