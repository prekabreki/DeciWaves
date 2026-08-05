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

## RESOLVED 2026-08-05: the oracle over-counts; only TWO scenes were really broken

The words-vs-duration check flags two different things and only one is a defect. To tell
them apart, render the scene with `--speech-trim ''` and measure the UNTRIMMED track.
Doing that overturned the first reading of these numbers.

**Not a defect -- the source track is simply shorter than its subtitle text.** Six
scenes. `sq_cs00_s00100` (the rope/stick opening narration) is a **25.8 s track, and
keepspans already keeps 24.7 s of it -- 96%.** It was never trimmed short. Its
`speech_ratio` of 0.132 looks alarming because that field is speech/total, but the kept
SPAN is essentially the whole track. Same story for `sq_cs03_s01300` (31.6 s track),
`sq_cs08_s00100` (163.3 s), `sq_cs06_s00350` (185.9 s), `sq_cs08_s01300` (296.4 s),
`sq_cs07_s00700` (82.0 s). The catalog holds more subtitle lines than a track's audio
contains -- alternate takes and variants -- so the word count over-estimates.

**So: a low `speech_ratio` is NOT evidence of truncation. Compare kept span against
TRACK LENGTH, never against word count.**

**A real defect -- `dropped=1` with `speech_ratio 0.0` on a track that does carry
dialogue.** ASR found no speech at all, so the row never renders:

| scene | track | audible | what it is |
|---|---|---|---|
| `sq_cs10_s00700` | 27.1 s, peak -21 dBFS | 1.04 s | Sam's "Lou." / "Louise." -- **the game's final beat** |
| `sq_cs03_s01000` | 10.0 s, peak -26.6 dBFS | 3.3 s | Cliff's "BB. BB." |

`sq_cs10_s00700` had **never rendered in any reel** -- checked v4, v5b and v6. Two quiet
words in a long near-silent track are exactly what an ASR gate discards.

## The repair, and its limits

An **RMS level gate** (-50 dBFS over 20 ms windows, 0.35 s padding, 0.5 s merge) finds
these, because it measures level rather than recognising words.
`scripts/ds1_patch_keepspans.py` in the workspace writes a patched copy to pass via
`--speech-trim`; the packaged data is left alone.

Use it **only** on `dropped=1` rows, and guard it. Applied to the six shorter-track
scenes it made every single one WORSE (`sq_cs07_s00700` 74.3 s -> 39.8 s) and shattered
them into 16-51 spans, which would sound chopped. The gate cannot distinguish speech from
any other sound and will cut mid-word at every brief dip -- ASR's ability to reject
non-speech is exactly what earns it its place on the other 162 rows.

Related: [[ds-speech-trim-is-load-bearing]], [[ds-cutscene-audio]],
[[ds-speech-spans-multiple-lines]].
