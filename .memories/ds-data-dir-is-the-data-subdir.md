---
description: "`--data-dir` for DS stages must be <install>/data, not the install root; the root has zero .bin files so PackIndex builds an EMPTY index and blames each individual stream — and a warm wav-cache disguises it as a category-specific format bug"
type: gotcha
---

Cost a misdiagnosis, a wrongly-filed issue (#409, closed invalid) and a wasted render on
2026-08-02. Worth not repeating.

## The fact

DS's 144 `.bin` archives live in `<install>\data\`. The install root holds **none**.
`PackIndex.__init__` globs `<data_dir>/*.bin`; given the root it constructs **successfully with
an empty index**, and every later `read()` raises
`ClipError: stream not in install: <path>` — per clip, naming the *stream* rather than the real
problem.

| `--data-dir` | index entries |
|---|---|
| `<install>` | **0** |
| `<install>\data` | **560,276** |

`games/ds/render.py`'s docstring already says `--data-dir <DS:DC/data>`.
**`deciwaves ds run` is unaffected** — `cli/config.py::resolve_ds_install` (L72) appends `data/`
itself. Only a hand-invoked stage can get this wrong. Guard filed as #414.

## Why it looked like a per-category format bug (the part worth remembering)

`engine/audio_clip.clip_wav` returns from the wav cache **before** it ever calls
`PackIndex.read`. `out/wav-cache` had been filled by an earlier `--main-story` render — cutscene
+ mission only. So with an empty index:

- `cutscene` + `mission` → cache hit, never touched the index, **100% success**
- `terminal` + `npc` → never previously rendered, no cache entry, straight to the empty index,
  **100% failure**

A flawless false signal for "these two categories are unreachable in this install", which is
exactly what #409 claimed. With the correct `--data-dir` all 6,588 playlist streams resolve —
3,114/3,114 terminal, 490/490 npc — and the full weave renders with 0 failures.

**Generalised:** when failures look cleanly category-specific, check whether the *successes*
came from a cache. A warm cache in front of a broken resolver manufactures a partial-failure
pattern out of a total failure. See [[ds-speech-trim-is-load-bearing]] for the other
silent-default trap on this same stage.

Related: [[ds1-story-reel-composition]], [[ds-transcript-anchoring-is-the-real-ordering]].
