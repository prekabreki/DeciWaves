# ASR binding plan: name the clips by content (issue #24)

**Status:** proposed (2026-06-26). An **offline, content-based** alternative to cracking the
structural `hi32` line→stream binding (`.memories/hzd-audio-gate.md`; runtime route #22/#15,
`docs/runtime-binding-plan.md`). Instead of recovering *which slot* a clip sits in, we recover
*what a clip says* and match that to a subtitle we already have.

## What this issue is, precisely

Two linkings get a labeled, chronological reel; they use different inputs and live in different
issues:

1. **Identity — WAV → which catalog line it is** (speaker + subtitle + scene). This is the hard
   part — the binding `hi32` would have given us structurally. **This is all #24 does.**
2. **Order — catalog line → chronological position.** Inherited from the matched line's scene
   code + gamescript (`docs/zero_dawn_gamescript.md`); **not** re-derived from audio. **That is
   #20** (manifest → ordered, silence-trimmed, rendered MP3 reel).

So #24 succeeds iff the **identity** match is good. Its deliverable is an **augmented manifest**
(`clip → line_id (+ speaker, subtitle, scene) + confidence tier`), not the MP3s.

## Why it's credible

- Game VO is studio-clean, single-speaker, English → Whisper is strong on it.
- It is a **constrained** match against a known list of subtitles, not open transcription.
- Targets exactly the deliverable subset: long, distinctive story lines match cleanly; the lines
  that collide by text ("Yes." / "Over here!") are the generic low-value ones.
- Non-speech clips (grunts, effort VO, the baby-cooing oracle) fail to match and drop out —
  which is correct.
- **Complementary to #15/#22:** if `hi32` is later cracked, ASR matches are a free cross-check,
  and vice-versa.

## The spine: hybrid `(A,B)` prefilter + ASR text-match

Pure text-matching against 67k subtitles is loose. We have an independent structural prior **for
free** from the SENTENCE parse, so we use both.

### The structural prior `(A, B)` — an exact join key, NOT a size filter

Each catalog line's SENTENCE resource exposes:
- **A** = exact encoded ATRAC9 byte-length (== the locator `length`).
- **B** = exact decoded sample-count (== vgmstream `SampleCount`).

Both were confirmed 1-in-millions against the oracle stream (`.memories/hzd-audio-gate.md`).
Every *extracted clip* also has an observed `(A, B)`. So a clip and a line either match on
`(A, B)` to the byte/sample, or they don't. This is a **join key**, not a "skip short clips"
threshold — nothing is dropped for being short.

Discriminating power: `A` alone is loose (median ~52 lines share any byte-length, max ~489), but
`B` is a largely-independent second number. `(A, B)` together typically narrows a clip from ~52
candidates to a small handful, often one. ASR then settles whatever ties remain.

**Prerequisite:** `A`/`B` are not in `catalog.csv` yet (cols today: `line_id, core_path,
line_index, category, scene, speaker_code, speaker_name, subtitle_en, wem_path_en, language`).
We emit them per line into a side table / new columns, and **verify coverage across the ~9,366
story lines** before leaning on the prior. If `(A,B)` coverage is thin for some lines, those fall
back to text-only matching within the full catalog.

### Pipeline

```
all package.01 locator entries (FwLocators.entries(archive=None), file order)
  → DSAR read(offset,length) → ATRAC9 .wem → VGAudioCli → WAV        [extraction, already solved]
  → VAD/energy triage (see below)
  → WhisperX large-v3 transcript
  → candidate lines = catalog lines whose (A,B) == clip's (A,B)      [structural prefilter]
  → rapidfuzz token-set ratio (normalized text) transcript vs each candidate subtitle
  → tiered acceptance → augmented manifest row
```

Extraction needs **no binding** — `package.01.00.core.stream` has ~67,853 entries (the installed
English slot), ≈ one clip per line. Clips are per-line (a long clip is one long line, not a scene
with dead air), so there is no "long cutscene, bit of talking" case to gate around.

## VAD / energy gate (in #24 — triage + confidence, NOT trimming)

- WhisperX runs VAD internally, so it already ignores silence when transcribing — we do **not**
  need a dB gate to get a clean transcript, and a crude -40 dB cut could clip quiet speech onsets.
- We add a **fast energy/VAD pass as pre-ASR triage**: clips with essentially no speech-band
  energy skip ASR entirely (real compute saved over 67k clips) and auto-bucket as non-speech.
- The speech-to-total ratio rides along as a **confidence feature** (90%-speech match > 0.3s-blip
  match).
- **Silence *trimming* for clean output is deferred to #20** (ffmpeg `silenceremove` + loudness
  normalization on the final MP3s).

## Compute / ASR engine

- **WhisperX + `large-v3` on the local RTX 3060 12GB.** `large-v3` fp16 fits with headroom;
  faster-whisper (CTranslate2) int8/float16 is lighter still and leaves room for batching.
  WhisperX adds batched inference + VAD (doubles as the triage gate) + word-level timestamps.
- ~67k short clips ≈ an overnight run, not multi-day. CPU-only would be an order of magnitude
  worse and is not the plan on this box.

## Match + collision policy

**Score** within each clip's `(A,B)` bucket: primary = normalized text similarity (`rapidfuzz`
token-set ratio; text lowercased, punctuation-stripped, whitespace-collapsed). `(A,B)` already
gates the bucket; VAD speech-ratio modifies confidence.

**Assignment is a uniqueness problem → tiered acceptance, not raw best-match:**

| Tier | Condition | Action |
|---|---|---|
| 1 — bind | unique strong match (≥90 sim) clearly ahead of runner-up in bucket | accept (ground-ish truth) |
| 2 — bind+flag | good match but close runner-up, or short generic line | keep, marked low-confidence |
| 3 — unbound | nothing clears threshold, or bucket ties | left explicitly unbound (non-speech lands here, correctly) |

Thresholds are starting points, tuned against the validation sample.

## Oracle & exit gate

The proven line (`MQ010_cut_Prologue_Dial_225`) is **useless for ASR validation** — it's 2:28 of
baby-cooing, no speech. Bootstrap a spoken anchor instead: extract a small batch, listen, identify
1–2 distinctive story lines by ear, confirm transcript matches the catalog `subtitle_en`.

**Exit gate:** coverage on the ~9,366 story-usable lines — what % land in Tier 1 — with precision
estimated from a hand-checked sample of ~30–50 bound clips. High coverage ⇒ this may reach the
deliverable faster than the runtime instrument (#22).

## Sequencing (MVP before the overnight run)

1. Emit `(A, B)` per line; verify story-line coverage of the prior.
2. **MVP:** few hundred clips end-to-end — extract → VAD triage → WhisperX → `(A,B)` bucket →
   rapidfuzz match → eyeball. Bootstrap + confirm a spoken oracle here.
3. Tune thresholds against a hand-checked sample.
4. Full overnight run over all ~67,853 package.01 clips → augmented manifest.
5. Hand off the manifest to #20 for ordering + render.

## Risks / open questions

- **`(A,B)` coverage** for story lines (verified in step 1); thin coverage ⇒ text-only fallback.
- **Ambiguity:** identical/near-identical subtitles can't be split by text alone → Tier 2/3 and a
  collision policy (accept only confident unique matches). Gamescript context is an optional
  tie-breaker, not the spine.
- **Heuristic, not ground-truth** like the runtime crack — fine for a labeled reel, but flag
  low-confidence matches.
- **Disk:** stream extract → ASR per clip to avoid tens of GB of WAV resident at once.

Relates: #15 (the binding), #20 (order + render), #22 (runtime RE), #23 (positional order test).
