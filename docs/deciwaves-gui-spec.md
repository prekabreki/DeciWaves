# DeciWaves GUI — Design Spec

A desktop GUI for **DeciWaves** (Windows-only Python tool that extracts story-ordered
voiceover from Decima-engine games: Death Stranding, Horizon Zero Dawn Remastered,
Horizon Forbidden West). **The GUI is the primary way people run this tool** — the
README's install command becomes `pip install "deciwaves[gui]"`, and the CLI remains
the engine underneath (and the power-user surface).

> **Verified against the repo as of 2026-07-17** (post issues #22/#31/#35/#36/#37/#38).
> Design decisions below were settled in a grill session on the same date; the
> decision log is §12.

> **Architecture rule:** the GUI does **not** re-implement the pipeline. All pipeline
> *mutations* (catalog, bind, order, render, setup) go through the `deciwaves` CLI as
> subprocesses. Because the GUI is in-process Python, it MAY import `deciwaves` as a
> library for **read-only** helpers — CSV parsing and the on-demand single-clip
> preview decode (`engine.audio_clip.clip_wav`, `games.hzd.atrac9.decode_wem_to_wav`)
> — the package's own functions, not re-implementations. When behaviour differs from
> this spec, the CLI is the source of truth.

> **One app, not three.** A single GUI adapts to the selected game via a swappable
> per-game panel (§7). The shared frame — line list, columns, core filters, MP3
> export, coverage — stays identical across all three games.

> **v1 scope:** ships with **all three games** working (a BYO user who only owns HZD
> must not bounce off a DS-only GUI), but development runs **DS-first** as the
> vertical slice — no GPU, simplest chain, fastest feedback — then HZD, then FW.

---

## 1. Framework, packaging, entry points

- **UI:** PySide6 (Qt Widgets). Native Windows desktop, worker-thread support for
  hours-long jobs, model/view tables that handle tens of thousands of rows, and the
  GUI stays in-process Python so it reuses `deciwaves`' own readers. PySide6 is LGPL,
  compatible with the repo's MIT license.
- **Lives in this repo** under `src/deciwaves/gui/`, shipped as the `[gui]` extra —
  the CSV/marker contracts the GUI depends on are tested in the same tree that
  defines them.
- **Entry points:**
  - bare `deciwaves` → launches the GUI when the `[gui]` extra is importable;
    otherwise falls back to today's guided prompt with a one-line
    `pip install "deciwaves[gui]"` hint. Guided mode stays (tiny, tested, the no-Qt
    fallback).
  - `deciwaves gui` — explicit subcommand.
  - `deciwaves-gui` — a `gui_scripts` entry point, so shortcuts launch without a
    console window.
  - `launch_gui.bat` — one-line repo-root shim (`py -m deciwaves.gui`) for git-clone
    users; a convenience, never the documented mechanism.
- **Distribution beyond pip** (post-v1): a standalone Windows download
  (PyInstaller or installer) is the right end-state for the gamer audience, but
  bundling the GPU stack (CUDA torch + whisperx, ~2.5 GB, needed for HZD/FW binds)
  is a hard packaging problem — tracked as its own exploration issue, not in v1.
- **Backend:** subprocess calls to `deciwaves ...` on worker threads; **one pipeline
  job at a time globally** (§5.3).
- **Data in:** the CLI's CSV artifacts (§6.1) plus resume markers
  `out/<game>/.done-<stage>`. GUI-owned state lives under `out/<game>/gui/` (§6.4,
  §8.1) — a namespace the pipeline never touches.
- **Config:** *reading* `%LOCALAPPDATA%\DeciWaves\config.json` directly is fine
  (respect `DECIWAVES_CONFIG_DIR`); *writing* only via `deciwaves setup` — which
  merges (omitted flag keeps the saved value, explicit `--flag ""` clears).
- **Testing:** pytest-qt with `QT_QPA_PLATFORM=offscreen` in the existing
  `windows-latest` CI job; GUI tests skip cleanly when the `[gui]` extra isn't
  installed, matching the repo's skip-clean test culture. Model/view and job-runner
  logic gets unit coverage; subprocess calls are faked the same way `cli/run` tests
  fake stage mains.

## 2. App structure: two views, one window

- **Pipeline view** — setup/doctor status, the per-game stage strip, job progress,
  log console, coverage + issues panel.
- **Library view** — the line list: search, filters, selection, preview, export.
  Enabled as soon as a catalog exists; usable *while later stages run* (§6.2).

Global bar (both views): game dropdown · install status line · workspace picker ·
job chip ("HZD · bind · 43%") — visible from everywhere, since the running job may
belong to a game other than the selected one.

---

## 3. First run: Setup & Doctor

- **Setup screen** runs `deciwaves setup` and shows one row per tool from setup's
  own summary statuses (`found / fetched / FAILED: reason`).
  - Setup **skips** already-installed tools (manifest-verified); "Re-download" =
    `--force`, offline "Re-check" = `--skip-downloads`.
  - No download progress is emitted — indeterminate spinner per tool (~200 MB cold).
  - The Oodle DLL is **located under the DS install**, not downloaded; a missing DLL
    is a setup WARNING worth surfacing.
- **Doctor panel** runs `deciwaves doctor --json` (prerequisite issue, §10) and
  renders the checks as a status list.
  - Doctor checks the `[asr]` extra and CUDA (informational, never fail the exit
    code) — the GUI *promotes* them to first-class readiness items for HZD/FW.
  - Unowned games report `not configured` — neutral, never a failure.
  - Every failing check carries its named fix; show it verbatim.
- **GPU nuance the CLI does not catch:** `run`'s GPU gate only checks that
  `whisperx` imports — CPU-only torch passes, then grinds for days. Before starting
  an HZD/FW bind, probe CUDA (doctor output or `torch.cuda.is_available()`) and show
  a blocking warning: *"No GPU visible — this stage may take days on CPU. Continue?"*

---

## 4. Game selection, install paths, workspace

- **Game dropdown:** Death Stranding, Horizon Zero Dawn, Horizon Forbidden West.
- **Status line:** on game select → green "installation found" / red "installation
  not found" / neutral "not configured".
- **Browse install:** folder picker → `deciwaves setup --ds-install` /
  `--hzd-package` / `--fw-package`. Setup merges, so setting one game never blanks
  another. Surface setup's own validation hints (e.g. HZD's "did you mean
  ...\LocalCacheDX12\package?" correction).
- **Workspace picker:** maps to the global `--workspace` flag. Hard rules:
  - `--workspace` comes **before** the game token
    (`deciwaves --workspace DIR hzd run`).
  - The GUI always passes **absolute paths** for every path-valued flag —
    sidestepping the CLI's relative-path absolutization heuristics entirely.
- Warn when changing workspace while artifacts exist in the old one.

---

## 5. Pipeline view

### 5.1 Stage strip — per game, exactly the chain `run` executes

Read `out/<game>/.done-<stage>` markers (markers live under `out/<game>/` for **all**
games, even though DS's CSV artifacts land in the `out/` root).

| Game | Chain (`<game> run`) | GPU stage | Standalone-only extras |
|------|----------------------|-----------|------------------------|
| DS   | catalog → order → render | none | `cutscenes`, `trim` (regenerate bundled cutscene data; `trim` is GPU) |
| HZD  | catalog → clip-index → wem-metadata → bind → render | bind | — |
| FW   | extract → asr → subtitle-bind → *(gamescript gate)* → match → full-reel → render | asr | `weave`, `dlc`, `assemble` (§7.1) |

- DS has no bind stage and its default chain needs **no GPU** (cutscene tracks and
  speech-trim keep-spans ship as packaged data).
- HZD/FW have **no standalone order stage** — ordering is embedded in bind/render
  (HZD) and match/full-reel (FW). The strip must not render a phantom "order".

### 5.2 Controls: Scan + Bind, re-runs from the strip

- **Two primary buttons.** **Scan** = `run --until <last pre-GPU stage>` (DS: the
  whole chain; HZD: through `wem-metadata`; FW: through `extract`). **Bind /
  Process** = `run` onward. The GPU-phase button carries the hours warning and the
  CUDA probe (§3).
- **Re-run:** right-click a stage in the strip → "Re-run from here" (= delete that
  stage's marker, invoke `run`; cascade invalidation of later markers is the CLI's
  own behavior — the GUI never cascade-deletes).
- **`run --until/--from` is a prerequisite CLI issue (§10)** — without it, `run`
  refuses to execute even the cheap pre-GPU stages on a machine lacking the ASR
  extra, and the GUI would have to run stages standalone and fake the marker
  contract itself. Build the flag first; the GUI never touches markers.
- **Changing `--sample-cap` is inert while `.done-bind` stands** — the coverage
  bar's "Transcribe all" escalation (§5.4) deletes the bind marker knowingly.

### 5.3 Jobs: one at a time, progress, cancel, resume

- **Exactly one pipeline job runs at a time, app-wide** — matches the one-GPU
  reality; one progress chip, one log console, one cancel target. The CLI's own
  `--jobs` flag already parallelizes within a stage. Preview decodes (§6.5) are not
  jobs and may run alongside — cached-WAV writes are atomic
  (`engine.atomic_io`), so preview and pipeline never corrupt a shared cache.
- **Progress contract:** don't scrape stdout for percentages — watch artifacts grow
  (`catalog-processed.txt` lines, `asr-transcripts.csv` rows vs. ambiguous-bucket
  count, wav-cache file count, output CSV row counts). Always show a collapsible
  **log console** with raw stdout/stderr per job: the CLI output is the ground
  truth, and hour-long jobs need visible motion.
- **Cancel is always safe — say so in the UI.** Artifact writes are atomic, stages
  have resume sidecars, an interrupted bind resumes from `asr-transcripts.csv`.
  Cancel = terminate the subprocess; the next run picks up where it stopped.

### 5.4 Coverage & issues panel

- **Coverage** ("4,812 / 5,001 lines bound · 96%") comes from the persisted coverage
  artifact (prerequisite issue, §10 — today these numbers are stdout-only, including
  the cap-skip count, so a capped rip looks complete on disk).
- Render coverage cap-aware: *"X/Y bound · Z ambiguous clips untranscribed —
  [Transcribe all (hours)]"*. The escalation button sets `--sample-cap 0`, deletes
  `.done-bind`, and re-runs — a deliberate, labeled hours-long action (§7).
- **Issues panel** data sources: per-stage `*-errors.log` files;
  `out/render-dupes.csv` (DS within-scene dupes). The one remaining *silent* drop —
  HZD `inventory.harvest_sentence_cores` skipping unreadable cores — has a
  prerequisite fix (§10).

---

## 6. Library view — the line list

Columns: **preview ▷ · checkbox · line id/name · length · speaker · subtitle**. All
rows checked by default. Status line always visible: *N checked · M visible · T
total*. **Default sort: story order once it exists** (DS `playlist.csv`, HZD bound
manifest, FW full-reel manifest) — the list should read like the reel will play;
artifact order before that. Every column header sorts.

### 6.1 Artifact map (what the GUI parses)

| Game | List source | Key columns | Landed by |
|------|-------------|-------------|-----------|
| DS   | `out/catalog.csv` | `line_id, category, scene, speaker_name, subtitle_en, wem_path_en, language` | catalog |
| DS   | `out/playlist.csv` (story order) | `episode, is_side, pos, scene, speaker, subtitle, stream_path, line_id` | order |
| HZD  | `out/hzd/catalog.csv` | same 10-column schema as DS; `wem_path_en` deliberately empty | catalog |
| HZD  | `out/hzd/asr-manifest.csv` | `clip_row, offset, line_id, speaker_name, subtitle_en, scene, tier, score, transcript` | bind |
| FW   | `out/fw/clip-index.csv` | `line_id, group_id, lssr_index, file_index, offset, clip_bytes, wav` | extract |
| FW   | `out/fw/subtitle-manifest-full.csv` → `out/fw/full-reel-manifest.csv` | `line_id, wav, speaker, subtitle, gamescript_index, quest, tier, score, transcript` | subtitle-bind → full-reel |

### 6.2 Data availability — honest per game and stage

| Field | DS | HZD | FW |
|---|---|---|---|
| line id | catalog | catalog | extract |
| speaker | catalog | **catalog** (lines are *not* anonymous pre-bind — only the clips are) | after `match` (BYO gamescript), matched lines only |
| subtitle | catalog | catalog | after `subtitle-bind` (BYO `types.json`) |
| audio / ▷ | on-demand decode any time after catalog | **only after bind** | WAVs on disk right after extract |
| length | **not stored in any artifact** — fill lazily | after bind (`b_samples` proxy); exact at decode | measurable from WAVs post-extract |

Consequences:
- **Length column:** show "—" until real values exist; fill lazily (FW: probe WAV
  headers post-extract; HZD: joinable after bind; DS: fill as rows get previewed or
  rendered). Disable the duration filter while empty.
- **Pre-bind HZD is a feature:** speaker + subtitle exist at catalog time — browse,
  search, and curate checkboxes *while bind runs*. Show ▷ and length as pending
  ("available after bind").

### 6.3 Search & filters (view-only — never touch checkboxes)

- **Search box** over subtitle text (and line id/name).
- **Speaker filter** dropdown — DS/HZD any time; FW meaningful post-match.
- **Hide duplicates** / **Hide no-subtitle** — expose the pruning the pipeline
  applies anyway (DS order drops within-scene exact dupes → `render-dupes.csv` and
  empty/`(none)` subtitles; HZD render skips `ambient`/no-subtitle rows). Label as
  "dropped at render by the pipeline" — unchecking the toggle shows them, it can't
  keep them in the reel.

### 6.4 Selection (one-shot commands with undo — separate from filters)

- **Persistence:** checkbox state lives in `out/<game>/gui/selection.json`, storing
  only unchecked `line_id`s (checked is the default). Survives restarts, travels
  with the workspace; corrupt/missing → everything checked.
- **Uncheck shorter than __ s** — enabled only once lengths exist (§6.2).
- **Uncheck barks** — there is **no `tier` bark flag**; `tier` is match-confidence
  (HZD `S/1/2/E/3`, FW `S/1/2/W/D`, DS none). Use the pipeline's own heuristics:
  HZD `category == "ambient"` or empty subtitle; FW no-subtitle (barks never bind)
  plus a word-count floor; DS empty-subtitle rows are already gone by order time.
- **Check all / none.**
- Selection actions never auto-reapply; each is explicit and undoable.

### 6.5 Inline preview ▷

- **FW:** open `out/fw/audio/<line_id>.wav` directly (exists right after extract).
- **DS:** on-demand decode via `engine.audio_clip.clip_wav(idx, stream_path,
  cache_dir)` — cached, already used per-track by the pipeline.
- **HZD:** disabled pre-bind; post-bind decode clip bytes via
  `atrac9.decode_wem_to_wav` using `clip-index` coords, written to render's own
  cache path (`out/hzd/wav-cache/<clip_row>.wav`) so render reuses it — safe to
  share, all cache writes are atomic.
- After any render, prefer the wav-cache over fresh decodes (caches persist).
- Desktop conventions: single playback at a time; space toggles checkbox, enter
  plays; keyboard navigation throughout; column widths and last game/workspace
  persisted.

---

## 7. Per-game panel (the adaptive part)

Same frame everywhere; only this panel swaps. Hide irrelevant controls rather than
greying them out.

| Control | DS | HZD | FW |
|---|---|---|---|
| GPU / bind block (progress, CUDA warning) | hidden (no GPU in default chain) | shown | shown |
| ASR sample cap | — | **default: capped (300)** — first bind reaches a listenable result fast; the coverage bar's "Transcribe all (hours)" escalation (§5.4) is the uncapped path, impossible to miss | — |
| Reference file: narrative transcript (BYO) → `ds order --transcript` | optional picker (standalone `order` only — not reachable through `ds run`) | — | — |
| Reference file: gamescript (BYO) → `setup --fw-gamescript` (persisted) | — | — | optional picker, high-value (speaker + story order) |
| Required file: `types.json` (BYO, from odradek) | — | — | required picker — gates **subtitle-bind onward**, not extract/asr; scan + preview work without it. Default location: workspace root. |
| Render scope | `--main-story` toggle (`ds render`) | `--spine-only` toggle (`hzd render`) | `--tiers` selector, default `1,2,S` (`fw render`) |
| Scan warning copy | "minutes, CPU" | "bind may take hours (GPU)" | "asr may take hours (GPU)" |

Notes:
- FW gamescript: a configured-but-missing path fails loud (exit 1); the picker still
  verifies existence at pick time as hygiene.
- The pipeline is **English-only by construction** — no language selector.

### 7.1 FW advanced assembly (post-v1)

`weave`, `dlc`, and `assemble` are real, working, standalone-only stages `fw run`
never invokes. Post-v1: an "Advanced assembly" disclosure in the FW panel (include
DLC reel / weave recovery → chain `dlc` + `weave` + `assemble`, point render at the
combined manifest). Not v1.

---

## 8. Output & export

Operates on **checked rows only**.

### 8.1 Selection → render: the filtered-manifest contract

Every render stage reads its input from an overridable path flag — DS
`ds render --playlist`, HZD `hzd render --manifest`, FW `fw render --manifest
--audio-root out/fw`. The GUI writes a filtered copy of the game's own
playlist/manifest CSV (rows = checked lines, columns unchanged) to
`out/<game>/gui/render-selection.csv` and points render at it. The CSV schemas are
the GUI↔CLI contract — already existing, already tested.

Export drives the **standalone render stage**, not `run` — `ds run` hardcodes
`--main-story --bitrate 96` and could never express these controls. Stage-strip
bookkeeping for the render stage comes from the GUI's job history, not markers
(export renders are parameterized one-offs by design).

### 8.2 Controls — truth in labeling

- **Export MP3** — render to reels + tracklist sidecars (`timestamp, scene/quest,
  speaker, subtitle, line_id`).
- **Bitrate selector** — **DS only** (`--bitrate`, default 128; GUI offers
  96/128/192). HZD/FW are hardcoded 128k — show a fixed "128k" label until the
  opportunistic flag lands (§10).
- **Split size** — not configurable; reels split automatically at ~285 MB
  (constant). Static text, no input field.
- **Dump WAV (selected rows)** — no CLI command exists; v1 uses the preview decode
  path (§6.5) per checked row into a user-chosen folder (DS `clip_wav`, HZD
  `decode_wem_to_wav`, FW file-copy). An upstream `dump` stage is the opportunistic
  CLI-clean version (§10).
- **Export catalog CSV** — copies the on-disk catalog (or the current filtered
  view) to a user-chosen location.
- Progress + **Cancel** on every job (§5.3 semantics).
- **Empty renders:** HZD/FW currently exit 0 having written zero reels (only DS has
  a guard) — the prerequisite guard issue (§10) makes all three exit non-zero, and
  the GUI surfaces that as an error, never a success.

---

## 9. Implementation gotchas (current, verified)

1. `--workspace` before the game token; always pass absolute paths (§4).
2. Never cascade-delete markers when driving `run` — it does that itself (§5.2).
3. The GPU gate blocks even pre-GPU stages without the ASR extra — hence the
   `run --until` prerequisite (§5.2).
4. `--sample-cap` changes are inert while `.done-bind` stands — the escalation
   button owns that marker deletion (§5.4).
5. GPU gate = "whisperx imports", not "CUDA works" — GUI adds its own probe (§3).
6. DS artifacts live in `out/` root; HZD/FW under `out/<game>/`; markers under
   `out/<game>/` for all three (§5.1).
7. All long stages run off the UI thread; cancel is safe and resumable everywhere
   (§5.3).

---

## 10. CLI work in this repo (no longer "upstream" — same codebase)

**Prerequisites — build before/alongside the GUI skeleton; each removes a GUI hack:**

| Change | Removes |
|---|---|
| `run --until <stage>` / `--from <stage>` | GUI-side marker bookkeeping; enables Scan/Bind split (§5.2) |
| persist coverage + cap-skip counts to a JSON/CSV artifact | stdout capture for the coverage bar (§5.4) |
| empty-render guard (exit ≠ 0) for HZD/FW | GUI post-render output checks (§8.2) |
| `doctor --json` | brittle text parsing in the Doctor panel (§3) |
| log + count skipped cores in `hzd inventory.harvest_sentence_cores` | the one silent drop the issues panel can't see (§5.4) |

**Opportunistic — GUI ships without them:**

- `--bitrate` on `hzd render` / `fw render` (global bitrate selector)
- `--target-mb` split flag (editable split field)
- `dump` stage: decode selected ids to WAV via the CLI

---

## 11. Post-v1

- Standalone Windows distribution (PyInstaller/installer; the CUDA/whisperx bundling
  problem is the crux — needs its own investigation).
- FW advanced assembly (§7.1).
- Scene/quest-grouped tree view for the line list (§12).

---

## 12. Decision log (grill session, 2026-07-17)

- Audience: **public BYO users** — first-run polish, doctor clarity, and error
  wording are features, not extras.
- v1 ships **all three games**; development is DS-first as the vertical slice.
- **CLI prerequisites first** (§10) — the GUI carries no interim hacks.
- **One pipeline job globally**; preview decodes run alongside (atomic cache writes
  make sharing safe — verified in `engine/atomic_io` call sites).
- Pipeline controls: **Scan + Bind** buttons, per-stage re-run via strip context
  menu.
- **GUI is the primary interface**; README leads with `pip install
  "deciwaves[gui]"`; bare `deciwaves` → GUI when importable, guided fallback;
  `deciwaves gui` + `deciwaves-gui` entry points; `launch_gui.bat` shim for cloners.
- HZD sample cap: **capped 300 by default** + visible coverage escalation
  (reverses the first draft's uncapped default).
- Selection state: **`out/<game>/gui/selection.json`**, unchecked-exceptions only;
  GUI-owned files namespaced under `out/<game>/gui/`.
- Line list: **story order when known**, artifact order before.
- Testing: pytest-qt offscreen in the existing `windows-latest` CI; GUI tests skip
  cleanly without the `[gui]` extra.
