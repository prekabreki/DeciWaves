# Architecture

This document is for anyone who wants to read, extend, or fix DeciWaves. It explains how
the code is organized, why the three supported games each needed a genuinely different
extraction strategy, and how the test suite is built to stay honest on a machine that
doesn't own any of the games.

DeciWaves turns proprietary Decima-engine game archives into speaker- and subtitle-tagged
voice-line manifests, then renders those manifests into story-ordered MP3 reels. The three
supported games are Death Stranding: Director's Cut (DS), Horizon Zero Dawn Remastered
(HZD), and Horizon Forbidden West (FW). They run on the same engine family, but each ships
its dialogue in a different container with a different way to recover speaker, subtitle,
and story order — so the codebase deliberately does not force one binding strategy across
all three. What's shared is the pieces that are *actually* common: archive readers, the
per-game configuration seam, and the tail of the pipeline (selection, ordering, rendering).

## Package layout

```
src/deciwaves/
  engine/          game-agnostic core: archive readers, the GameProfile seam,
                   the shared catalog/selection/story_order/render pipeline
    pack/          per-archive-format byte readers
  games/
    ds/            Death Stranding specifics
    hzd/            Horizon Zero Dawn Remastered specifics
    fw/            Horizon Forbidden West specifics
  cli/             the `deciwaves` console-script entry point: stage dispatch,
                   workspace handling, persisted tool/install config
  _vendor/
    pydecima/      a patched, MIT-licensed Decima .core reader, bundled in-tree
  data/            small, non-prose packaged data files (ID/timing manifests, name rosters)
tests/             the test suite (mirrors the src/ layout)
```

`deciwaves.engine` is "game-agnostic" in the sense that nothing under it hardcodes a single
game's paths or vocabulary — but it earns that status per-module, not by decree. Some
engine modules (`catalog.py`, `story_order.py`) still lean on Death-Stranding-shaped
defaults and reach into `deciwaves.games.ds` for a couple of constants; that's a known
rough edge, not a hidden design goal. Treat `engine/` as "the code more than one game
uses today," not as a strict abstraction boundary.

## The `GameProfile` seam

`deciwaves.engine.profile.GameProfile` is a frozen dataclass that carries the knobs a
game-agnostic module needs without hardcoding a specific game's paths:

- `pack_reader` — the object that knows how to read this game's archives.
- `decima_version` — the string passed to the vendored pydecima reader (e.g. `"DSPC"`).
- `core_prefixes` — a `{virtual_path_prefix: category}` mapping used to select and classify
  which `.core` files hold dialogue.
- `speaker_simpletext_filter` — a predicate that picks out the per-voice files used to
  resolve human-readable speaker names.

Those four fields are the ones actually read off a `GameProfile` today
(`engine/catalog.py`, `games/hzd/catalog.py`, `games/hzd/wem_metadata.py`). The dataclass
also declares `name`, `transcript_path`, `out_dir`, `episode_map`, and `cutscene_resolver` —
five more fields with no current profile-level reader. The DS code that plays their role
(`engine/story_order.py`, `games/ds/episode_map.py`, `games/ds/cutscene_audio.py`) imports
the DS module directly instead of going through the profile, so passing those fields on a
profile object doesn't currently do anything. Trimming `GameProfile` down to the four
consumed fields is tracked in issue #24 — don't take the extra five as a contract a fourth
game needs to fill in.

Each game builds its own profile from a `build_profile(...)` factory
(`games/ds/profile.py`, `games/hzd/profile.py`) that supplies its own prefix map and
filter. Forbidden West doesn't build a `GameProfile` at all today — its pipeline is
different enough (positional index, not sentence-core scanning) that forcing it through
the same seam would cost more than it would save. If you're adding a fourth game, look at
what HZD actually reads off the profile before assuming you need every field.

## The pipeline: catalog → selection → story_order → render

The DS and HZD pipelines share this shape (FW's is described in its own section below):

1. **Catalog** (`engine/catalog.py` for DS, `games/hzd/catalog.py` for HZD) — walk the
   game's dialogue resources and emit one CSV row per voice line: a stable line ID, the
   source `.core` path, category/scene, speaker code and display name, the English
   subtitle, and a path to the encoded audio stream. This stage is resumable (it skips
   `.core` paths already present in the output CSV) and fail-soft (a parse error on one
   file is logged and skipped, never aborts the run).
2. **Selection** (`engine/selection.py`) — a small, portable set of creative rules applied
   to catalog rows before ordering: drop rows with no subtitle or no audio stream, and
   drop within-scene duplicate `(scene, speaker, subtitle)` triples while keeping the same
   line if it recurs in a different scene. This is deliberately factored out of
   `story_order` so a future profile can reuse it without copying the logic.
3. **Story order** (`engine/story_order.py`) — turns the filtered catalog plus (for DS)
   cutscene track rows into an ordered playlist. Where a user-supplied narrative
   transcript is available it anchors scenes to their real chronological position;
   everywhere else, episode/scene heuristics place the line. A `GameProfile` with an empty
   `transcript_path` (the shipped default — DeciWaves does not bundle any game's script
   text) falls back cleanly to the heuristic order.
4. **Render** (`engine/render.py`) — packs the ordered playlist into MP3 files sized to
   stay under a fixed per-file budget (comfortably under 290 MB per file at a given
   bitrate), inserting small silence gaps between lines and a longer one between scenes,
   and writes a tracklist CSV alongside each MP3 so the reel is navigable.

HZD reuses the general shape of catalog/render — `games/hzd/render.py`'s own docstring
notes it reuses `engine.render`'s game-agnostic packing/concat (`pack_episodes`, silence
gaps, `_ffmpeg_concat`) — but it does **not** reuse `engine.selection`: nothing under
`games/hzd/` imports `filter_and_dedup` or anything else from that module. Instead HZD has
its own binding stage in place of both DS's transcript anchoring and DS's
`engine.selection` dedup — its structural (A, B)-bucket join (see below) binds at most one
line to one clip per bucket by construction, which is a different mechanism from, not a
reuse of, `filter_and_dedup`. The two games don't share `story_order.py` itself.

## Command-line interface

The package declares a single console-script entry point (`deciwaves`, see
`pyproject.toml`) pointing at `deciwaves.cli.main:main`, giving every stage a uniform
`deciwaves [--workspace DIR] <game> <stage>` invocation — or, with no subcommand at all, a
guided interactive flow (see below).

- **Guided mode (bare `deciwaves`).** The primary entry point for someone who just wants to
  point the tool at a game and get a reel, not memorize stage names. Running `deciwaves`
  with no subcommand runs `deciwaves/cli/guided.py`, which reuses the same pieces the
  explicit subcommands use rather than reimplementing them: it prints which games
  `doctor.py`'s own install checks (`check_ds_install` / `check_hzd_package` /
  `check_fw_package`) consider configured, prompts for a game and a workspace directory,
  `chdir`s into that workspace, and calls the identical
  `deciwaves.cli.run.run_game(...)` that `deciwaves <game> run` calls. If stdin isn't a
  TTY (CI, a pipe, a scripted invocation) it never blocks on `input()` — it prints a
  one-line usage hint and returns a nonzero exit code instead.
- **Stage dispatch.** `deciwaves/cli/main.py` keeps a `STAGES` registry — a
  `{game: {stage_name: (module_path, help_text)}}` mapping covering every stage in all
  three pipelines (DS: `catalog` / `cutscenes` / `trim` / `order` / `render`; HZD:
  `catalog` / `clip-index` / `wem-metadata` / `bind` / `render`; FW: `extract` / `asr` /
  `subtitle-bind` / `match` / `full-reel` / `weave` / `dlc` / `assemble` / `render`). Each
  stage module already exposes its own `main(argv=None) -> int`, and dispatch is exactly
  `importlib.import_module(module_name).main(rest)` — the CLI doesn't reimplement stage
  logic or flags, it just imports the right module and calls its `main`. If you're looking
  for where a given stage's flags are defined, read the `argparse` block at the bottom of
  that stage's own module, not the CLI layer.
- **Workspace.** `--workspace` (default `.`) is resolved to an absolute path, created if
  it doesn't exist, and the process `chdir`s into it before a stage runs. Stage modules
  default their own outputs to CWD-relative `out/` paths (this is also why FW's
  `subtitle-bind` stage can default `--types-json` to a bare `types.json`: it resolves
  against whatever directory `--workspace` chdir'd into), so this `chdir` is what lets one
  flag redirect an entire run without touching every stage's individual path arguments.
- **Config env application.** `deciwaves/cli/config.py` persists a small JSON config
  (`tools_dir`, `ds_install`, `hzd_package`, `fw_package`, `oodle_dll`) under
  `%LOCALAPPDATA%/DeciWaves/config.json` (overridable via `DECIWAVES_CONFIG_DIR`).
  Before dispatching to any stage, `main()` calls `_apply_config_env()`, which prepends
  the saved `tools_dir` onto `PATH` and sets `DECIWAVES_VGMSTREAM` / `DECIWAVES_VGAUDIO`
  when the corresponding executables are found there. `engine/audio_clip.py`,
  `games/fw/extract.py`, and `games/hzd/atrac9.py` all read those environment variables
  via `engine/tool_paths.py`'s `resolve(env_var, exe)` at the moment the decoder
  subprocess is actually spawned, so stage-module import order relative to
  `_apply_config_env()` doesn't matter.
- **`setup`.** `deciwaves setup` (`deciwaves/cli/setup.py`) fetches `vgmstream-cli`,
  `VGAudioCli`, and `ffmpeg` into a tools directory (default
  `%LOCALAPPDATA%\DeciWaves\tools`), locates `oo2core_7_win64.dll` under a supplied
  `--ds-install`, and persists all of that — plus any `--hzd-package` / `--fw-package`
  paths — via `deciwaves/cli/config.py`. Each tool's download/unpack is isolated (one
  failed fetch is reported in the summary table and doesn't stop the others), but the
  command exits nonzero overall if any tool ended up missing.
- **`doctor`.** `deciwaves doctor` (`deciwaves/cli/doctor.py`) runs a set of small,
  independently-testable `(ok, message)` checks — the decode tools, the Oodle DLL, each
  game's install/package path, the optional ASR extra, and CUDA availability — and prints
  a report. The exit code is 0 only when every *required* check passes; an unconfigured
  game (the user simply doesn't own it) reports `[--] not configured` but its check
  reports `ok=True` regardless, so `doctor` never requires a DS (or HZD, or FW) install to
  report a clean bill of health. The ASR extra and CUDA checks are purely informational
  either way.
- **`<game> run`.** Each per-game subparser accepts `run` alongside its real stage names,
  as a whole-pipeline shortcut (`deciwaves/cli/run.py`): `ds run` chains `catalog -> order
  -> render`; `hzd run` chains `catalog -> clip-index -> wem-metadata -> bind -> render`;
  `fw run` chains `extract -> asr -> subtitle-bind`, then — only once a `--gamescript`
  (BYO; see `docs/BYO.md`) is supplied — continues `match -> full-reel -> render`. The
  GPU-bound stages in those chains (`hzd bind`, `fw asr`) are gated on
  `importlib.util.find_spec("whisperx")` and print an actionable install hint (`pip
  install deciwaves[asr]`, plus a matching PyTorch build) instead of crashing when the ASR
  extra isn't installed. **Resume is per-stage**: once a stage's `main()` returns `0`,
  `run` writes a done-marker file at `out/<game>/.done-<stage>`, and a later `run`
  invocation skips any stage whose marker already exists (delete the marker to force a
  re-run of just that stage). A stage's own output path or directory existing is
  deliberately *not* treated as "done" — a crash-interrupted run's partial output, or one
  stage's output directory being mistaken for another's, must never look like a finished
  stage. Each `run` subcommand builds its own `argparse` parser for its own flags (e.g. `ds
  run --data-dir/--oodle`, `fw run --package/--gamescript`), so `deciwaves <game> run
  --help` prints that game's actual flags instead of falling through and starting the
  multi-hour pipeline.

## Death Stranding: Director's Cut

DS dialogue is described by Decima resources, not by a familiar audio container. A
`SentenceGroupResource` holds `SentenceResource` entries, each pointing at a
`LocalizedSimpleSoundResource` that carries, per language, a *virtual path* ending in
`.wem.<language>`. Two things fall out of that:

- **Identification, subtitles, and speaker are a Decima parsing job.** DeciWaves reads
  DS `.core` files with a bundled, patched copy of `pydecima` (`deciwaves/_vendor/pydecima`,
  the DSPC patch applied in-tree so a fresh checkout never needs a separate vendoring
  step). `engine/sentence_core.py` walks a parsed `.core`'s `SentenceGroupResource`
  objects, follows each sentence's voice/text refs, and emits one `Line` per voice line.
- **The encoded payload is Wwise, not a Decima-native format.** The `.wem` extension is
  Wwise's own container, and the install ships the matching Wwise infrastructure
  alongside the Decima resources. So turning a resolved `.wem` stream into a playable WAV
  is a Wwise decode job (`vgmstream-cli`), layered underneath the Decima parse rather than
  replacing it. Treat "parse the resource" and "decode the payload" as two separate steps
  with two separate tools, because the game does.

A second finding shapes how DS content is classified: **story cutscenes are staged
in-engine, not pre-rendered video.** Their dialogue lives in the exact same
`localized/sentences/` tree as codec calls and incidental chatter, distinguished only by
internal resource-name prefixes (`games/ds/profile.py`'s `DS_CORE_PREFIXES` maps path
prefixes like `ds_lines_cutscene` / `ds_lines_mission` / `ds_lines_npc` to a category).
Because a cutscene's line-level sound refs are null, its audio is resolved per *scene*
instead of per *line* — `games/ds/cutscene_audio.py` locates the scene's whole-track Wwise
voice file(s) under a separate Wwise cinematics path and hands them to
`engine/speech_trim.py`, which computes speech-region keep-spans (from an externally
supplied speech-segment list) so dead air and back-to-back grunts between cues get
trimmed out of the rendered track. Pre-rendered video (studio logos, recaps, credits) is a
small, separate, optional pass outside this workflow.

## Horizon Zero Dawn Remastered

HZD Remastered ships its dialogue resources in the newer Forbidden-West-style package
format (`PackFileLocators.bin` + numbered `package.NN.NN.core[.stream]` archives), not
DS's encrypted archive format — so DS's pack reader does not apply, and HZD gets its own
byte-level readers under `engine/pack/`. HZD also does not expose a packfile file listing
the way DS does, so `games/hzd/inventory.py` harvests sentence-core paths by content
scanning the package rather than reading a table of contents, and
`games/hzd/sentence_fw.py` is a **self-contained tolerant byte parser** — it does not go
through pydecima at all, because HZD's resource layout diverges enough from DS's that
reusing the DS-oriented Decima reader would cost more than a small dedicated parser.

The interesting problem in HZD is **binding an anonymous decoded audio clip back to the
catalog line it belongs to**, when the runtime linkage that would normally answer that
question isn't available offline. The fix is a structural join that needs no audio
decode and no transcription for the vast majority of lines:

- Every catalog line and every audio clip can cheaply expose a pair **(A, B)** — A is the
  clip's encoded byte length, B is its decoded sample count (read from the codec's header,
  not by fully decoding). `games/hzd/sentence_fw.py` extracts (A, B) per line;
  `games/hzd/atrac9.py` extracts it per clip.
- `games/hzd/binding.py` buckets every line and every clip by their `(A, B)` key. A bucket
  that contains exactly one line and one clip binds **structurally** — no ambiguity, no
  ASR needed. In practice this resolves the large majority of story lines for free.
- Only buckets with more than one candidate ("collision buckets" — usually where several
  near-identical clips or lines share the same byte/sample counts) go to speech
  recognition. `games/hzd/asr.py` wraps WhisperX; `games/hzd/match.py` scores each
  transcript against each candidate subtitle with fuzzy string matching (guarding against
  a known failure mode where a short candidate's tokens are trivially a subset of a long
  transcript, which would otherwise score as a false 100% match) and assigns tiers by
  confidence; a final elimination pass pairs off any bucket left with exactly one
  unmatched line and one unmatched clip. `games/hzd/asr_bind.py` orchestrates the whole
  worklist and writes the bind manifest. Because ASR only ever runs on the ambiguous
  minority of clips, the GPU-bound stage stays small relative to the size of the game.

## Horizon Forbidden West

Forbidden West ships neither DS's archive format nor a usable runtime linkage the way HZD
lacks one — but it does ship something HZD does not: a single large `streaming_graph.core`
resource (`engine/pack/fw_streaming_graph.py`) that indexes every archive, every audio
locator, and every object group in the game. That resource is what makes FW's pipeline
possible: a `SentenceResource`'s group in the streaming graph exposes a **positional
index** into a locator table — the group's audio locators are consumed in the same walk
order as the group's other objects, so the English `LocalizedDataSource` locator for a
given line can be located without needing an external runtime hook. `games/fw/extract.py`
walks this positional index end to end to batch-decode English dialogue clips to WAV
(FW's payload is plain RIFF/ATRAC9, unlike DS's Wwise-wrapped `.wem`, so decode is a direct
codec call).

Labeling those decoded clips is a separate problem from finding them, because a group's
subtitle order, audio order, and sentence order are three independently-shuffled
sequences — you cannot assume the k-th subtitle belongs to the k-th clip. The fix is
**exact-subtitle labeling**: `games/fw/subtitle_bind.py` reads every in-game English
subtitle in a group (an exact, game-authored string, not a transcription) and recovers
the within-group pairing by greedily assigning each subtitle to its best-scoring
transcript from a lightweight local transcription pass — a small disambiguation step
scoped to one group's handful of candidates, not a transcript-wide search. The subtitle
itself, not the transcript, becomes the shipped label, so the result is exact game text
rather than an ASR paraphrase; groups with no subtitle at all (mostly barks and combat
chatter) are naturally excluded. From there, `games/fw/subtitle_match.py` optionally
matches those exact subtitles against a user-supplied gamescript to recover speaker names
and precise story position for the lines the script covers; `games/fw/story_full.py` and
`games/fw/weave.py` build full-reel orderings that keep matched groups at their
script-anchored position and cluster everything else by scene; `games/fw/dlc.py` and
`games/fw/assemble.py` fold in expansion content and concatenate the final manifest before
render.

## Testing philosophy

The suite is built so that it stays green — by skipping rather than failing — on any
machine, including CI runners that own none of the three games:

- **Synthetic fixtures for binary parsers.** Archive- and resource-format readers are
  exercised against hand-built byte strings assembled with `struct.pack`, not real game
  files, so their size-exact assertions and boundary conditions (truncated input, an
  unexpected field value) are testable without a game install
  (`tests/test_dsar_archive.py`, `tests/test_atrac9.py`, `tests/test_fw_object_reader.py`,
  and others follow this pattern).
- **Install-gated skips, not failures, for anything needing a real install.**
  `tests/conftest.py` defines fixtures like `require_install`, `fw_package_dir`, and
  `pr201_core_bytes` that call `pytest.skip(...)` when the expected install directory or
  a derived fixture file isn't present, rather than letting the test error out. A test
  that needs a real DS or FW install, or a regenerated fixture, opts into one of these
  fixtures instead of hardcoding a path.
- **Environment-variable overrides, never hardcoded personal paths.** Install locations
  and external tool paths are resolved through `DECIWAVES_*` environment variables with
  sane public defaults, so a contributor's own install and tool locations never need to
  be hardcoded or committed:
  - `DECIWAVES_DS_INSTALL` — DS: Director's Cut install root (defaults to the standard
    Steam path).
  - `DECIWAVES_FW_INSTALL` — Forbidden West install root (no public default; FW tests skip
    without it).
  - `DECIWAVES_VGMSTREAM` / `DECIWAVES_VGAUDIO` — explicit paths to the `vgmstream-cli`
    and `VGAudioCli` decode tools, falling back to whatever `PATH` resolves.

## Running the suite

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
python -m pytest -q
```

Because the patched `pydecima` reader is bundled in-tree under
`deciwaves/_vendor/pydecima`, an editable install is enough to get a fully importable DS
engine — no separate vendoring step. Expect a mix of passes and install-gated skips on a
machine that doesn't own the games; the parser- and logic-level tests (including the
bundled-pydecima layout tests) should pass regardless.
