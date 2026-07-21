# DeciWaves GUI — UX & Architecture Audit

_Audit date: 2026-07-18 · Target: `src/deciwaves/gui/` (PySide6 Qt Widgets desktop app) · Method:
read the full GUI tree + spec, ran the app headless (`QT_QPA_PLATFORM=offscreen`, PySide6 6.11.1) for
cold-start/layout/empty-state observation, traced the threading model deliberately, cross-verified every
High/Critical against source. Four parallel read-only agents covered distinct rubric slices; all
Critical/High findings were re-checked by hand._

## 1. Executive summary

**Overall UX-health grade: B− — a genuinely sound architecture with a first-run/operational UX that is
not yet shippable-polished for the stated public "bring-your-own-game" audience.** The engineering
foundation is strong and rare: a real `QAbstractTableModel` behind a virtualized view, all pipeline work
off the UI thread via `QProcess`, atomic state writes, a GPU probe that catches the real CPU-only-torch
failure, honest truth-in-labeling, and a headless CI test suite. But a cluster of operational gaps would
bite a first-time user hard.

**The app was run** (headless, cold-start with an empty config). Top 5 issues:

1. **[CRITICAL]** Pipeline jobs (scan/bind/render, hours long, on the one GPU) **cannot be cancelled from
   the UI** — `JobRunner.cancel()` is fully implemented but wired to no button. Contradicts spec §5.3.
2. **[HIGH]** No `closeEvent`: closing the window mid-bind can **orphan the CLI child** (GPU held, no
   window), with no "job running — quit anyway?" confirmation.
3. **[HIGH]** **Pipeline job failures are silent** — a failed scan/bind sets the chip to `idle` exactly
   like success; the only cue is a raw traceback scrolling in the log.
4. **[HIGH]** **Choosing a workspace does nothing** — no `workspace_changed` signal, so the central BYO
   action leaves every panel showing stale data until an unrelated event.
5. **[HIGH]** **Library freezes on refresh for FW** — every WAV header is probed synchronously on the UI
   thread, re-run on tab-switch and after every job; plus no empty-state, and search resets the model
   (losing scroll + selection) on every keystroke.

Honorable mention: the window has a **hard ~1614 px minimum width** and won't shrink (breaks 1366×768 and
1080p-at-125%), and **FW export silently drops checked W/D-tier rows** (existing #106, more severe than
filed).

## 2. Architecture & screen inventory

**Package:** `src/deciwaves/gui/` (~3,830 LOC). Clean, deliberate split — Qt-free model modules
(`*_model.py`) hold all logic (argv construction, CSV parsing, filter/sort, coverage/issue parsing,
selection); thin widgets (`views/*.py`) render. This is the codebase's biggest strength and makes most
logic unit-testable without Qt.

**Entry points:** `deciwaves` / `deciwaves gui` / `deciwaves-gui` / `launch_gui.bat` → `gui.launch()` →
`app.run_app()` → `MainWindow` (`shell.py`). Import-safe without PySide6 (guided CLI fallback survives a
base install).

**Screens (one window, global bar + two tabbed views):**
- **Global bar** (`global_bar.py`): game dropdown · install-status line · workspace picker · job chip.
- **Pipeline view** (`views/pipeline.py`, `pipeline_panels.py`): Setup screen (runs `deciwaves setup`),
  Doctor panel (runs `deciwaves doctor --json`, auto-runs once on first show), per-game stage strip,
  Scan/Bind controls, log console, coverage bar, issues panel.
- **Library view** (`views/library.py` + `library_model.py`): the line list — a custom
  `QAbstractTableModel` (`_TableModel`) behind a virtualized `QTableView`; search, speaker filter,
  hide-dupes/no-subtitle toggles, per-row ▷ preview, checkbox selection, export panel.
- **Adaptive per-game panel** (`views/game_panel.py` + `game_panel_model.py`): swaps controls per game
  (hides, never greys); GPU/ASR-cap/pickers/render-scope vary by DS/HZD/FW.

**Threading model (traced):** correct at the core. Pipeline jobs and setup/doctor run as child processes
via `QProcess` (`jobs.py` `JobRunner`, `capture.py` `CaptureRunner`) driven by the Qt event loop — the UI
never blocks on them. Inline preview decode and the WAV dump batch run on `QThreadPool`/`QRunnable`
workers (`preview.py`, `export.py`) and marshal results back via main-thread-affine signals (queued, not
`DirectConnection`). One documented exception blocks the UI thread: **`LibraryView.refresh()` →
`load_lines()`** parses the whole per-game CSV synchronously and, for FW, opens+reads every WAV header
(see §3).

**Backend integration:** the GUI does not re-implement the pipeline — all mutations shell out to
`deciwaves <game> <stage>` and it reads the CLI's CSV artifacts + `.done-<stage>` markers. Read-only
imports (preview decode) are sanctioned; two resolution/join rules have leaked into the GUI as copies
(§4, backend-of-truth). One pipeline job runs at a time app-wide, enforced at every runner entry point.

## 3. Responsiveness verdict (the headline)

Every long-running operation, and whether it blocks the GUI thread:

| Operation | Transport | Blocks UI thread? |
|---|---|---|
| Pipeline scan / bind / render / order | `QProcess` (`JobRunner`) | **No** ✅ |
| `setup` (~200 MB fetch) / `doctor --json` | `QProcess` (`CaptureRunner`) | **No** ✅ |
| Inline preview decode (incl. first DS `PackIndex` build, ATRAC9/wem→wav) | `QThreadPool` `_ResolveWorker` | **No** ✅ |
| WAV dump batch | `QThreadPool` `_DumpWorker` | **No** ✅ |
| **Library refresh** (`load_lines` — whole-CSV parse; FW: WAV-header probe per row) | **GUI thread** | **YES** 🔴 |
| Export-MP3 prep (2–3 full CSV passes) | GUI thread | Yes (bounded, one click) 🟠 |
| Catalog export (`shutil.copyfile`) | GUI thread | Yes (bounded, one click) 🟠 |

The one clear freeze is **Library refresh on FW**: `library_model.py:186,200` call
`wav_duration_seconds()` (`:229-267`, an `open()` + RIFF walk) for *every* row, and `refresh()` fires on
game-change, on tab-switch into Library (`shell.py:190-191`), and on every job finish (`shell.py:286`) —
i.e. at its most expensive exactly when an FW `extract` finishes and tens of thousands of WAVs now exist.
This directly contradicts the spec's "length … filled lazily" design. DS/HZD avoid per-row I/O but still
parse the entire CSV on the UI thread. Concurrency policy ("one job at a time") is correctly enforced; the
one concurrency hole is a *shared decoder handle* between preview and dump (§4, High), not a runner race.

## 4. Findings by severity

Each finding: location · Fact/Suspicion · impact · fix · effort (S/M/L).

### CRITICAL

**C1 — Pipeline jobs cannot be cancelled from the UI**
`jobs.py:46-54` (cancel implemented) · `views/pipeline_panels.py:129-131` (`set_running` only *disables*
Scan/Bind) · `shell.py` (no call to `self.runner.cancel()`; grep-confirmed — only `dump.cancel` is wired,
`shell.py:99`). **Fact.** `JobRunner.cancel()` implements the spec's terminate→kill contract exactly, but
nothing invokes it: there is no Cancel button and no `cancel_requested` signal. An hours-to-days HZD/FW
bind on the single GPU has **no in-app stop** — the user's only recourse is to kill the window (which
orphans the child, H1). Directly violates spec §5.3 ("Cancel is always safe — say so in the UI"). _Fix:
add `cancel_requested` to `PipelineControls`; while running, turn Bind/Process (or a dedicated button)
into "Cancel" wired to `runner.cancel()` — mirror the Dump button's `set_dumping` toggle
(`export.py:136-141`)._ **Effort: S.**

### HIGH

**H1 — No `closeEvent`: closing mid-bind orphans the CLI child (GPU held)**
`shell.py` (no `closeEvent`; grep: no `aboutToQuit`/`waitForFinished`) · confirmed at runtime
("has closeEvent override: False"). **Fact** (absence) + **Suspicion** (orphan outcome on Windows
`~QProcess` teardown). Closing during a bind leaves teardown to interpreter-exit destruction ordering; on
Windows this frequently leaves `python -m deciwaves.cli.main … run` running detached, holding the GPU with
no window. No "a job is running — quit anyway?" confirm. Also the dump pool worker isn't awaited, so an
in-flight `shutil.copyfile` (`export.py:234`) can leave a truncated `.wav`. _Fix: `MainWindow.closeEvent`
— if `runner.is_running`, confirm; on accept `runner.cancel()` + `waitForFinished(grace)`, `dump.cancel()`
+ `QThreadPool.globalInstance().waitForDone(timeout)`, then accept._ **Effort: M.**

**H2 — `JobRunner` emits `started` before confirming launch and ignores `errorOccurred` → UI wedged**
`jobs.py:42-44` (unconditional `started.emit()`, no `errorOccurred` connection) · contrast `capture.py:55,
82-87`. **Fact.** On `FailedToStart`, QProcess fires only `errorOccurred`, never `finished` — so
`_on_job_finished` never runs: chip stuck "running", the 1.5 s poll timer loops forever, all controls stay
disabled (`_sync_running`), no recovery short of restart. `CaptureRunner` already fixed this exact mode;
`JobRunner` didn't. _Fix: connect `errorOccurred`; on `FailedToStart` clear `_proc` and emit
`finished(-1)`._ **Effort: S.**

**H3 — Pipeline live-console runner lacks the UTF-8/unbuffered child env**
`jobs.py:30-44` (no `setProcessEnvironment`; decodes as UTF-8 at `:59`) · contrast `capture.py:15-22,50`
(`PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`). **Fact** (missing env) + **Suspicion** (buffering lag).
The *primary*, most-watched, hours-long console gets no env, so on Windows the child's non-ASCII output
(em-dashes, clip names, BYO paths) becomes replacement chars — the same class as #59, which `CaptureRunner`
explicitly guards. Neither runner sets `PYTHONUNBUFFERED`, so a block-buffered CLI could make the "live"
console lag or dump in bursts. _Fix: factor `_utf8_environment()` into a shared helper and use it in
`JobRunner`; add `PYTHONUNBUFFERED=1` to both unless the CLI already flushes._ **Effort: S.**

**H4 — Library refresh blocks the UI thread (whole-CSV parse + per-row FW WAV probe)**
`library_model.py:186,200,229-267` · driven from `views/library.py:242,252` + `shell.py:176-179,286`.
**Fact.** See §3. Multi-second freeze on large FW libraries with no spinner, worst right after `extract`.
_Fix: move `load_lines()` (at least the WAV-header probe) to a `QThreadPool` worker as done for
preview/dump, delivering rows via signal; or keep `length_s=None` at load and fill lazily via a background
pass emitting `dataChanged` for the length column only; cache durations keyed by path+mtime._ **Effort: M.**

**H5 — Search does a full model reset (loses scroll + current row) with no debounce**
`views/library.py:64-67` (`set_rows` uses `beginResetModel`/`endResetModel`), `:226,293-301` · haystack
rebuilt per row per keystroke at `library_model.py:272-291`. **Fact** (reset behavior; lag magnitude is
Suspicion at the high end). Every keystroke rebuilds the lowercased haystack over the whole dataset, sorts,
and **resets the model** — discarding the view's scroll position and current index, so the current row that
Enter-preview/Space-toggle depend on is cleared mid-type and those keys silently no-op until re-navigation.
At tens of thousands of rows typing also visibly lags. _Fix: debounce (~150–200 ms `QTimer`); precompute a
per-row search haystack once at load; use `layoutChanged` + persistent-index remap (or a
`QSortFilterProxyModel`) instead of `beginResetModel` so scroll/current-row survive._ **Effort: M.**

**H6 — No empty state and no distinct no-results state (primary view is a blank grid on first run)**
`views/library.py` (the `QTableView` has no placeholder/overlay; status only at `:445-446`) · confirmed at
runtime (empty workspace → `rowCount=0`, no guidance). **Fact.** A brand-new user (no catalog yet) sees an
empty grid and "0 checked · 0 visible · 0 total" with no cue to run Scan; a filter matching nothing looks
identical. This is the single most visible onboarding gap. _Fix: paint a viewport overlay with two texts
keyed on `total==0` ("No catalog yet — run Scan on the Pipeline tab") vs `total>0 and visible==0` ("No
lines match — [Clear filters]")._ **Effort: S.**

**H7 — Global-bar install status paints "not configured" alarm-red, and by color alone**
`shell.py:158-161` (`ok = check.status is Availability.OK`) · `global_bar.py:57-59` (green `#167f3b` if ok
else red `#b00020`, no glyph). **Fact.** Launch pins the game to DS (`shell.py:145`). A `NOT_CONFIGURED`
install — the *normal* state for a game the user doesn't own — is `ok=False` and renders identical to a
genuinely broken install, in the most prominent always-visible element. The text literally reads "not
configured (fine if you don't own it)" while blaring red. Contradicts the "unowned reads neutral, never
failure" principle the Doctor panel honors (`doctor_model.py:88-89`). Also the one status signalled by
color alone (no glyph, unlike Doctor's `● ✕ ▲ —`). _Fix: three states keyed on `Availability` (OK→green,
NOT_CONFIGURED→neutral grey, BROKEN→red) + a leading glyph; default launch game to last-used/first-owned._
**Effort: S.**

**H8 — Choosing a workspace has no immediate effect (no `workspace_changed` signal)**
`global_bar.py:64-68` (`_pick_workspace` sets text, emits nothing), `:18` (only `game_changed` exists) ·
no listener in `shell.py` (grep-confirmed). **Fact.** Browse/typing updates the `QLineEdit` but fires no
signal; `_workspace()` is read lazily, so status, stage strip, coverage, issues, Library, and game panel
all keep showing the *previous* workspace's data until an unrelated event (game change, tab switch, job
finish). The central BYO action appears to do nothing. _Fix: add `workspace_changed` (on Browse-accept and
`editingFinished`); connect to `_refresh_status/_refresh_panels/_refresh_library/_refresh_game_panel` +
resolver invalidation._ **Effort: S.**

**H9 — Destructive "Re-run from here" and "Transcribe all" fire with no confirmation**
`shell.py:250-257` (`_on_rerun` → `run --from <stage>`, cascade-invalidates later markers), `:259-266`
(`_on_escalate` → `run --from bind --sample-cap 0`, drops `.done-bind` + full uncapped re-transcribe).
**Fact.** The only gate is `_confirm_gpu`, which prompts *solely when no GPU is visible* — so on a normal
GPU machine a stray click on "Transcribe all" instantly discards a completed capped bind and launches the
single most expensive operation in the app (hours-to-days). The brief explicitly lists "re-run that wipes
markers, escalate that deletes .done-bind" as must-confirm. _Fix: confirmation dialog for escalate ("This
re-transcribes every line uncapped — hours. Continue?") and for re-run when completed later markers would
be invalidated._ **Effort: S.**

**H10 — Pipeline job failures are effectively silent**
`shell.py:273-288` (non-export branch never inspects `code`) · contrast `:300-309` (export surfaces rc).
**Fact.** A failed scan/bind/order/re-run sets the chip to `idle` exactly like success and refreshes
panels; the only evidence is whatever scrolled by in the raw merged log — so a Python traceback becomes the
de-facto primary error UI. For a public audience this is the difference between "it worked" and "it
silently did nothing." _Fix: branch on `code` for pipeline kinds too — emit a plain-language "… failed (rc
N) — see log" and set a distinct "failed" chip state._ **Effort: S.**

**H11 — Window has a hard ~1614 px minimum width and won't shrink (clips on common displays)**
Observed at runtime: `minimumSize`/`minimumSizeHint` = 1614×628, `sizeHint` = 1806×750; `resize(1000,600)`
snapped back to 1614×628. Attributed to non-wrapping single-row content — `ExportPanel` (min 1230,
`export.py:71-79`), a ~1128 px non-wrapping `QLabel`, and `GlobalBar` (min 1328, `global_bar.py:30-37`); no
explicit `setMinimumSize` anywhere (`app.py:16-17` bare `show()`). **Fact** (min-size + clamp measured) +
**Suspicion** (exact clipping at each DPI). On 1366×768 laptops and 1080p-at-125% (1536 logical px) the
window exceeds the screen and the right edge — part of the export controls — is unreachable because it
can't shrink. Real for a public gamer audience. _Fix: `setWordWrap(True)` on the long help labels; wrap the
export row into two rows / a `QFormLayout`; give the workspace field a min width; set a sane explicit
`setMinimumSize`._ **Effort: S–M.**

**H12 — FW export silently drops checked W/D-tier rows at default settings** _(existing #106 — more severe than filed)_
`shell.py:327` (`**self.game_panel.render_scope()`) · `game_panel_model.py:44` / `views/game_panel.py:271`
(`render_scope()` always returns concrete `{"tiers": "1,2,S"}`, never `None`) · `export_model.py:175`
(`scope_tiers = tiers if tiers is not None else _fw_tiers(...)` — so the panel value *replaces* the
present-tier union). **Fact.** Because the panel never sends `None`, the "keep every checked row" union
path (`_fw_tiers`, `:195`) is dead code from the GUI: a user who checks a Weave (`W`) or DLC (`D`) line and
hits Export gets it silently dropped. The Library has **no tier column** (`views/library.py` — zero `tier`
refs) and there is no warning, so the drop is invisible. Violates the module's own "export renders EXACTLY
the checked rows" contract (`export_model.py:12-19`). DS `--main-story`/HZD `--spine-only` default OFF
(keep everything), so FW is the lone asymmetric default. The existing test
`test_fw_explicit_tiers_replace_union_and_can_drop_a_row` *codifies* the drop, masking it. _Fix: make the
FW default a true no-op — `render_scope()` returns `{"tiers": None}` unless the user edits the field (so
the union path runs), or prefill the field from the present-tier union; and/or warn when checked rows carry
an out-of-scope tier before rendering. Add a guard test that the default preserves all present tiers._
**Effort: M.**

**H13 — Preview and Dump share one stateful `PreviewResolver` and can decode concurrently**
`shell.py:195-207` (single cached resolver), `:338-348` (dump uses `self._preview_resolver()`), `:293`
(`_sync_running` deliberately leaves preview enabled during a dump) · `preview_model.py:118-123,148,154-157`
(unlocked lazy `PackIndex`/`HzdPackage`/dsar; `dsar.read(offset, nbytes)` seeks a shared file handle) ·
`export.py:231`. **Suspicion** (needs confirmation `PackIndex`/`HzdPackage` aren't safe for concurrent
reads). Clicking ▷ during a dump puts two pool threads into `resolver.resolve_wav()` against one shared
decoder — concurrent seek+read on a single handle can interleave into garbled bytes (the *output* write is
atomic; the *input* read is not synchronized). The lazy caches also use check-then-set with no lock
(double-build race). _Fix: give the dump batch its own resolver instance, or guard `resolve_wav`/handle
access with a lock; confirm thread-safety of the readers._ **Effort: M.**

### MEDIUM

**M1 — No session persistence at all (no `QSettings`)** _(consolidated: columns, geometry, last game/workspace)_
Grep: zero `QSettings`/`saveGeometry`/`restoreState` in `gui/`; `app.py:16-17` bare `show()`; game
hard-pinned to DS (`shell.py:145`); header configured once, only `COL_SUB` stretched
(`views/library.py:207-210`). **Fact.** The spec calls for persisting column widths and last game/workspace;
none exists. Every launch resets geometry, column widths, sort, workspace (→ `.`), and game — compounding
H7 (HZD-only owner sees red DS every launch) and H8 (must re-Browse every session). _Fix: a `QSettings`-
backed store for geometry + `QHeaderView` state + last workspace + last game, restored in `__init__`, saved
in `closeEvent`; keep separate from the `out/<game>/gui/` pipeline-adjacent state._ **Effort: M.**

**M2 — No guided first-run; workspace silently defaults to `.` (launch CWD)** _(overlaps #112)_
`views/setup.py:165-224` (no explanatory copy), `shell.py:155-156` (`workspace() or "."`),
`global_bar.py:26` (empty field). **Fact.** A new user sees a red status, an empty workspace field, three
unlabeled Setup buttons over `—` rows, and no "start here"/no "Run setup downloads ~200 MB" cue. Worse, the
`.` default means all `out/<game>/` reads/writes land wherever the process started — invisible and
unchosen. _Fix: a one-line intent banner on Setup; force an explicit workspace pick on first launch (or show
the resolved absolute workspace path prominently instead of an empty field)._ **Effort: M.**

**M3 — Setup failure-to-start / non-zero exit not surfaced; buttons never disable during a run**
`views/setup.py:226-235,269-291,240-242` (`is_busy` defined, consulted nowhere) · `capture.py:82-87`
(`FailedToStart` → `finished(-1,"")`). **Fact.** On failure-to-launch the tool rows reset to `—` and paths/
warnings blank with no message; there's no "setup exited with code N" line; and Run/Re-download/Re-check
never disable during a run. If setup dies before printing a summary the panel just looks empty. _Fix: on
`code != 0` with no parsed rows render an explicit error row; disable the buttons while `_busy`._ **Effort: S.**

**M4 — Doctor run shows no progress; the panel is blank for seconds during the torch import**
`views/setup.py:98-116,143-162`. **Fact.** `render_payload` only runs on `finished`; `doctor --json`
imports torch for `cuda.is_available()` (commonly 5–10 s cold), during which the panel is just a header over
blank space, and Re-check neither disables nor indicates activity (a second click silently no-ops). _Fix: a
"Checking…" placeholder row / disable + spinner on Re-check for the run's duration._ **Effort: S.**

**M5 — Setup / Doctor runs have no Cancel wired and aren't in the shutdown path**
`views/setup.py:180-185` (Run/Re-download/Re-check only), `:237-238` (`cancel()` exists, unwired) ·
`capture.py:61-67`. **Fact.** The ~200 MB cold fetch runs behind indeterminate spinners with no stop; a
wedged/unwanted download can't be cancelled from the UI, and no `closeEvent` terminates it on quit. Lower
than C1/H1 because it's read-only/idempotent. _Fix: a Cancel button while `_busy` wired to
`SetupScreen.cancel()`; include both capture runners in the `closeEvent` teardown._ **Effort: S.**

**M6 — Setup runs on its own runner, not mutually excluded from pipeline jobs**
`shell.py` (`_sync_running:289-298` covers runner/dump/export, not setup) · `views/setup.py:176`. **Suspicion.**
`Re-download --force` could run concurrently with a bind reading the very tools being refetched; nothing
enforces exclusion. _Fix: fold `setup.is_busy` into `_sync_running` (both directions)._ **Effort: S.**

**M7 — Export-MP3 can report success over a no-op empty selection**
`shell.py:300-309,313-336` (no `checked_count>0` pre-check, unlike Dump at `:343-345`) ·
`export_model.py:31-32,82-118` (writes header-only CSV; render "no-ops on empty input"). **Suspicion**
(depends on render's empty-input exit code). If empty render exits 0, `_report_export_result` prints the
confident "export: done — reels … written under out/…" over a no-op (the rc≠0 branch itself hedges "an
empty selection … can also cause this"). This is the success-over-no-op anti-pattern. _Fix: guard on
`checked_count>0` with a "nothing selected to export" message; verify render's empty-input rc (see the
spec §8.2 empty-render-guard prerequisite)._ **Effort: S.**

**M8 — Export-MP3 prep and catalog copy do synchronous multi-pass file I/O on the GUI thread**
`shell.py:320,325-327,366` · `export_model.py:104-117,195-210` (`_fw_tiers` re-reads the just-written CSV).
**Fact.** One Export click does, before the QProcess launches: a full source read + atomic filtered write,
then (FW) a second read of that CSV; catalog export is a synchronous `shutil.copyfile`. Perceptible hitches
on large FW manifests; bounded per click. _Fix: compute the tier union during the single write pass; run the
catalog copy on the pool._ **Effort: S.**

**M9 — Backend-of-truth: DS install resolution and the HZD manifest-join are duplicated in the GUI**
`preview_model.py:104-107,159-176` · `export_model.py:186-192` · CLI source `cli/run.py:334`,
`games/hzd/render.py`. **Fact.** The DS `data/` + hardcoded `oo2core_7_win64.dll` fallback is re-implemented
in three places; the HZD `line_id→clip_row→(offset,a_bytes)` join is re-implemented in preview. Preview
*decode* is sanctioned, but these resolution/join *rules* are pipeline logic the GUI now owns copies of —
silent drift if the CLI changes the DLL name or join semantics. _Fix: one shared read-only helper (e.g.
`config.resolve_ds_install(cfg) -> (data_dir, oodle)`) imported by both GUI modules and the CLI._ **Effort: M.**

**M10 — Preview affordance: availability signalled by color alone; long subtitles truncated with no tooltip**
`views/library.py:106-107,113-123` (same `▷` glyph, only gray vs default distinguishes unavailable; click
on unavailable is a silent no-op at `:359`; no `Qt.ToolTipRole` for the subtitle/id column, no
`setTextElideMode`). **Fact.** Colorblind/low-vision users can't tell playable from pending without hovering
each cell; long subtitles (common) are silently elided with no way to read them, defeating the
search-over-subtitle view. _(Overlaps #109's "too small" affordance point — this adds the color-only + no-
tooltip angles.)_ _Fix: differentiate the glyph itself (filled `▶` playable vs dimmed/hollow); a
pointing-hand cursor on available rows; return full text for `Qt.ToolTipRole` on subtitle/id._ **Effort: S.**

**M11 — MainWindow is trending toward a god-object (fat controller)**
`shell.py` (371 lines). **Fact/opinion.** The window owns `JobRunner`, `DumpRunner`, `PreviewPlayer`, the
resolver cache, the poll timer, *and* is the sole controller for every flow (scan/process/rerun/escalate/
transcript-order, all three export flows, preview, GPU gating, all refreshes). Business logic is cleanly
delegated to `*_model.py` (the strength), but the orchestration (`_on_export_mp3`, `_on_process`,
`_sync_running`, `_on_job_finished`) is only reachable by building the whole window — every shell test does.
_Fix: extract a `JobController` (owns runners + gpu-gate + dispatch/mutual-exclusion, plain methods) so it's
testable without a window; leave `MainWindow` as wiring._ **Effort: M.**

**M12 — GUI test coverage gaps**
`tests/gui/` (no `test_global_bar.py`) · `tests/gui/test_export_model.py:323`. **Fact.** (a) `global_bar.py`
has no dedicated test — the workspace Browse intent and `set_install_status` coloring are only touched
incidentally, so the workspace-picker path is effectively zero-covered (and H7/H8 have no guard). (b) No
test that FW's *default* export preserves checked W/D rows; the only tier test asserts the drop is intended,
so H12 has no guard. _Fix: add `test_global_bar.py` (monkeypatched `getExistingDirectory`, status color/ok);
add an FW default-tiers guard test (will currently fail, documenting H12)._ **Effort: S–M.**

### LOW

**L1 — Status-color hex duplicated across four files, light-theme-only**
`global_bar.py:59`, `views/game_panel.py:48-51`, `views/pipeline_panels.py:26-29`, `views/setup.py:46-49`
(same green/red/amber/grey by hand, applied via `setStyleSheet("color: …")`). **Fact.** Drift hazard +
poor contrast on a dark Windows theme (half-themed feel). _Fix: one `gui/theme.py` constants module; derive
from `QPalette` or add a dark variant._ **Effort: S.**

**L2 — StageStrip context menu leaks a `QMenu` per right-click**
`views/pipeline_panels.py:97-102` (`QMenu(self)` parented to the long-lived strip, never released). **Fact.**
_Fix: `WA_DeleteOnClose` or `deleteLater()` after `exec`._ **Effort: S.**

**L3 — Every checkbox toggle does a full atomic disk write + O(n) recount**
`views/library.py:315-322,442-443,418-427`. **Fact.** One Space press → atomic rewrite of the whole
unchecked set, an O(n) recount, and export-gate `isfile` checks; rapid toggling = one disk write per
keypress (can stutter under AV / slow disks). _Fix: debounce `save_selection`; track the count
incrementally; cache export-gate booleans per refresh._ **Effort: S.**

**L4 — Bulk selection commands silently ignore the active filter**
`views/library.py:332-343` (pass `self._rows`, not `self._visible`). **Suspicion** (design ambiguity). A
user filtered to one speaker who clicks "Check none" unchecks hidden rows too. Undo mitigates. _Fix: label
scope explicitly ("Uncheck all barks") or add scoped variants._ **Effort: S.**

**L5 — Preview decode is superseded but not truly cancelled**
`preview.py:93-116`. **Fact.** A stale result is dropped via a generation token and `stop()` stops the sink,
but the in-flight `_ResolveWorker` runs its decode (incl. an expensive first DS `PackIndex` build) to
completion — wasted work, can't be abandoned. Fine for single clips. _(Related to #100 nit #3.)_ _Fix:
optional cooperative cancel flag._ **Effort: S.**

## 5. Healthy areas (no action)

- **Model/view architecture** — real `_TableModel(QAbstractTableModel)` behind a virtualized `QTableView`;
  no `QTableWidget`/`QListWidget` anywhere (grep + runtime confirmed). `data()` hot path is syscall-free
  (O(1) set/dict lookups). Filter/sort run over the full dataset; the N/M/T counts are correct per scope.
- **Selection semantics** — stored as an unchecked-exception set, atomic writes, corrupt/missing →
  everything checked (per spec); filters never mutate checkboxes.
- **Threading foundation** — pipeline + setup/doctor via `QProcess` off-thread; preview + dump via
  `QThreadPool`; cross-thread results delivered through queued main-thread-affine signals (no
  `DirectConnection`); no two-runner start race; one-job-at-a-time enforced at every entry point.
- **GPU probe** — `cuda_probe.needs_gpu_warning` reads Doctor's real `torch.cuda.is_available()` result, so
  CPU-only-torch (imports fine, returns UNAVAILABLE) correctly triggers the blocking "may take days"
  dialog, and fails safe on a missing payload. This is the correct design and beats the CLI gate.
- **Doctor rendering** — fixes shown verbatim; severity keyed on `status`, not message text;
  NOT_CONFIGURED neutral; `[asr]`/`cuda` promoted to WARN for HZD/FW only; rows carry glyph + color;
  Setup↔Doctor status reconciled; Doctor auto-runs once on first show (guarded).
- **Truth-in-labeling** — bitrate is DS-only with a fixed "128k" label for HZD/FW; split-size is static
  text, not a field; the per-game panel *hides* (never greys) irrelevant controls, model-driven and tested.
- **Data safety** — `selection.json` + `render-selection.csv` atomic-written; correct `out/<game>/gui/`
  namespacing; config writes only via `deciwaves setup` (incl. BYO picker persistence); BOM handled.
- **CI/testing** — ruff + skip-clean base install + headless offscreen GUI tests; subprocess pipeline jobs
  faked; the runner mechanism exercised with a real trivial subprocess.

## 6. Prioritized remediation order (impact ÷ effort)

**Do first — cheap, high user impact (all S):**
1. **C1** wire a Cancel button to `runner.cancel()` — the one Critical, an S fix.
2. **H2** `JobRunner` `errorOccurred` → `finished(-1)` (stops the wedge).
3. **H10** surface pipeline-job failure (branch on `code`, "failed" chip).
4. **H7** three-state neutral install status + glyph.
5. **H8** `workspace_changed` signal → refreshes.
6. **H9** confirm "Transcribe all" / cascade re-run.
7. **H3** UTF-8 + unbuffered env for `JobRunner`.
8. **H6** Library empty + no-results states.

**Do next — small/medium, prevents data-loss & freezes:**
9. **H1** `closeEvent` (cancel + await workers, confirm; folds in **M5**).
10. **H4** Library refresh off the UI thread / lazy length (biggest freeze).
11. **H11** wrap labels + explicit min size (broadens the addressable audience).
12. **H12** FW default `--tiers` no-op (+ **M12** guard test) — real data-loss.
13. **H5** debounce search + stop resetting the model.

**Then — robustness & polish:**
14. **M1** `QSettings` persistence (geometry/columns/last game+workspace).
15. **M2** first-run guidance + explicit workspace (dovetails with #112).
16. **H13/M6** resolver/setup concurrency isolation.
17. **M3/M4** setup/doctor progress + failure surfacing.
18. **M7/M8** export empty-selection guard + off-thread prep.
19. **M9/M11** de-duplicate backend rules; extract `JobController`.
20. **M10 + L1–L5** affordance/tooltip, theme palette, menu leak, write debounce, cancel niceties.
