# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this repo is

DeciWaves extracts speaker- and subtitle-tagged in-game voice audio from **your own,
legitimately owned PC copies** of three Decima-engine games, and assembles it into
story-ordered MP3 reels:

- **ds** — Death Stranding (Director's Cut), parsed via a bundled, patched `pydecima`.
- **hzd** — Horizon Zero Dawn Remastered, parsed by a self-contained byte reader (no
  `pydecima` — a newer engine generation, different resource/archive formats entirely).
- **fw** — Horizon Forbidden West, resolved via its `streaming_graph.core` positional index.

**Definition of done (per game):** a manifest CSV where each row is a voice line with a
stable ID, internal name, speaker (where derivable), category/scene, language, and a path to
a playable WAV — rendered into ≤290 MB story-ordered MP3 reels.

**Architecture:** `src/deciwaves/engine/` is the (largely) game-agnostic core — archive/pack
readers, the `GameProfile` config seam, and the catalog → selection → story_order → render
pipeline; `src/deciwaves/games/{ds,hzd,fw}/` hold the per-game specializations. The three
games share an engine, but each required a genuinely distinct extraction/binding solution —
**true cross-game agnosticism is a non-goal**; the shared seam earns its keep only for what is
genuinely common across all three. See [`docs/architecture.md`](docs/architecture.md) for the
full contributor-facing walkthrough (package layout, the `GameProfile` seam, the pipeline, and
a one-pager per game).

## Build & test

```bash
pip install -e .              # base install: parsing, archives, catalog, render
pip install -e ".[asr]"       # + optional GPU ASR extra (WhisperX; needs a CUDA-matched torch)
pytest -q
```

Tests that need a real game install, a regenerated fixture, or a Wwise/ATRAC9 decoder binary
skip cleanly (`pytest.skip(...)`) when the dependency is absent, so the suite runs green on
any machine with just the base install. Point tests at real resources with environment
variables rather than editing test code:

- `DECIWAVES_DS_INSTALL` — path to a DS:DC install (enables DS integration tests).
- `DECIWAVES_FW_INSTALL` — path to a Forbidden West install (enables FW integration tests).
- `DECIWAVES_VGMSTREAM` / `DECIWAVES_VGAUDIO` — path to the Wwise `.wem` / ATRAC9 decoder
  executable (falls back to `PATH` lookup; several tests skip without one).
- `DECIWAVES_DS_TRANSCRIPT` — path to a local DS narrative transcript, for the (optional)
  transcript-anchored story-ordering tests.
- `DECIWAVES_CONFIG_DIR` — override where the CLI's `setup`/`doctor` commands read/write
  local tool-path configuration.

The CLI itself (`deciwaves ds|hzd|fw <stage>`, plus `deciwaves setup`/`deciwaves doctor`) is
declared as a console-script entry point in `pyproject.toml`; run `deciwaves --help` after
installing, or invoke a stage module directly as `python -m deciwaves.<module>`.

## Key format findings that drive the design

1. **Decima resources WRAP Wwise `.wem` audio (DS) — both layers matter.** Dialogue is
   *described* by Decima resources (`SentenceResource` → `LocalizedSimpleSoundResource` →
   text/voice/sound refs), so identification, subtitles, and speaker are a Decima parsing job.
   But the *encoded audio payload itself* is Wwise `.wem` — decoding it needs a Wwise-aware
   decoder (`vgmstream-cli`/`ww2ogg`), not a generic Decima resource reader. See
   [`.memories/ds-wwise-wem-format.md`](.memories/ds-wwise-wem-format.md).
2. **Story cutscenes are real-time / in-engine, not pre-rendered video.** Cutscene dialogue
   sits in the same resource tree as codec/terminal/NPC chatter, distinguished only by
   internal scene naming — not in video files. Its *audio*, though, is not per-line: each
   cutscene scene resolves to a small number of whole-scene Wwise voice tracks. See
   [`.memories/ds-cutscene-audio.md`](.memories/ds-cutscene-audio.md).
3. **HZD and FW need entirely different pack/audio-binding solutions from DS and from each
   other.** HZD Remastered ships a newer, unencrypted archive format with no positional
   ordering index, so its audio binding is solved by content fingerprinting; Forbidden West
   ships a positional streaming-graph index instead, solved by replaying deserialization
   order. See [`.memories/hzd-pack-format.md`](.memories/hzd-pack-format.md),
   [`.memories/hzd-structural-binding.md`](.memories/hzd-structural-binding.md), and
   [`.memories/fw-streaming-graph.md`](.memories/fw-streaming-graph.md).

## Constraints & gotchas

- **Windows-only.** Tooling (PowerShell hooks, the decoder binaries this project shells out
  to) targets Windows; no cross-platform support is maintained.
- **Bring your own game.** This repo ships code, never game content. It is read-only against
  any install it touches — it never repacks or modifies game files.
- **No game prose in the repo.** Narrative transcripts/gamescripts are copyrighted game text
  and are never checked in; they're an optional, user-supplied ("BYO") local input, wired
  through a `transcript_path` that defaults to `""` (disabled) per game profile.
- **Extracted audio stays out of git.** WAV/`.wem`/`.at9`/`.bk2`/manifests derived from a real
  install are gitignored; only small packaged sample/reference data ships in `src/deciwaves/data/`.
- **Treat format details as "likely," not "certain."** All three games' formats are partially
  reverse-engineered from empirical inspection, not from official documentation.

## Task tracking & work environment

This repo tracks work with **GitHub Issues** and keeps durable project knowledge in
**`.memories/`** (grep-friendly markdown).

### Issues

```bash
gh issue list --state open
gh issue view <N>
gh issue create --title "..." --body "..." --label "P2,bug"
gh issue edit <N> --add-assignee @me
gh issue close <N> --comment "<reason>"
```

### Memories (`.memories/`)

Durable, grep-friendly project knowledge — one fact per file, committed and shared.

- Each memory is `.memories/<kebab-key>.md`, opening with YAML frontmatter: `description:`
  (one line, required — feeds the index) and `type:` (optional, free-form).
- `.memories/README.md` is an **auto-generated index** — never hand-edit it. After adding or
  changing a memory, run `tools/memory-index.ps1` (or just commit — the `.githooks/pre-commit`
  hook, wired via `git config core.hooksPath .githooks`, runs it automatically and stages the
  refreshed index).
- Save a memory when a fact cost real effort to learn and isn't obvious from the code or git
  history. One fact, one file. Link related memories with `[[other-key]]`.
