# GUI onboarding & guidance layer — the guide rail (issue #112)

**Date:** 2026-07-21
**Issue:** [#112](https://github.com/prekabreki/DeciWaves/issues/112) — part of GUI epic #78
**Status:** Design approved; ready for implementation planning.

## Problem

The GUI pipeline works end to end (catalog → order → render, with working WAV preview),
but a first-time BYO user gets almost no guidance. The stages are not self-evidently
ordered; the Pipeline view is a long, fully-expanded stack (Setup + the whole Doctor list);
jargon (BYO, cores, segments, cutscene groups, dupes) is unexplained inline; and optional
checks (CUDA / ASR extra / `fw_gamescript` / `fw_types`) can read as failures rather than as
"not needed for the selected game." This is a coherent onboarding *layer*, not one widget.

The mechanical sub-items were already carved out and merged separately: workspace
tooltip/placeholder + control tooltips (#138), the "not configured" alarm-red fix (#122),
the `workspace_changed` wiring (#123), and the Library empty-state (#121). This spec covers
the judgment-heavy remainder.

## Acceptance (from the issue)

A first-time user knows what to do, in what order, understands each field, and never
mistakes an optional/absent extra for a broken install.

## Approach

A **state-aware guide rail** (an always-present, non-blocking step strip) with the inline
annotation pieces (help-icons, optional pills, first-run declutter) folded in. Rejected
alternatives, considered during brainstorming:

- **Passive/inline only** — better labels and less clutter, but a lost first-timer still has
  to infer the order themselves. Adopted *in part* (the inline pieces), but insufficient alone.
- **Dismissible first-run wizard/overlay** — strongest hand-holding, but a distinct mode to
  build and test, and can feel heavy. Rejected: the "recommended order of operations"
  checklist item is literally asking for a persistent sense of sequence, which a rail gives
  without a separate mode.

The rail doubles as the "recommended order of operations" panel **and** the compact
first-run readiness summary, so those two checklist items collapse into one widget.

## Section 1 — The guide rail

### Placement & scope

A slim horizontal `GuideRail` widget sits **between the global bar and the tab bar** in the
shell layout (`shell.py`: added after `self.bar`, before `self._tabs`), so it is visible on
both the Pipeline and Library views. The Setup → … → Export journey spans both tabs, so the
rail must too.

The rail reflects the journey for the **currently-selected game + workspace**. It is
recomputed by the same `_refresh_*` fan-out that already fires on game change, workspace
change, and job finish — no new polling.

The existing per-game `StageStrip` (#69) inside the Pipeline tab is **left untouched**. The
rail and the strip live at deliberately different altitudes:

- **Rail** = "where am I in the whole journey" (coarse, app-wide, includes pre-pipeline
  setup and post-pipeline export).
- **StageStrip** = "detailed pipeline-marker state" (fine-grained, per-game, Pipeline tab).

The mild overlap in the middle (Scan/Bind appear in both) is intentional and helpful — the
rail's "Scan" is a coarse journey step; the strip's is fine-grained marker state.

### Steps

The issue's list `setup → doctor → pick game → workspace → scan → bind → curate → preview →
export` collapses to the six steps that are *actually completable*:

```
Setup → Workspace → Scan → Bind → Curate → Export
```

- **Doctor** is not a step — it is the readiness *check* behind Setup's done-state.
- **Pick game** is not a step — the dropdown is always set; instead the rail is *scoped* to
  the current game (see "game-not-owned state").
- **Preview** folds into Curate (done while curating, not a discrete gate).

### Completion logic

All derived from existing state; the rail never writes markers or config.

| Step | "Done" when |
|---|---|
| Setup | required tools (vgmstream, VGAudio, ffmpeg) present in the latest `doctor --json` payload |
| Workspace | `bar.workspace()` is non-empty **and explicitly chosen** (closes M2 — no silent `.` default) |
| Scan | `.done-<scan_target>` marker exists under `out/<game>/` |
| Bind | all pipeline markers present (`stage_states` all done) |
| Curate | lenient — never blocks; "available" once Bind is done |
| Export | a `playlist.csv` / reel file exists under `out/<game>/` |

### The one live button (interaction model)

Only the **first not-done step** renders as a live button; every other step is an inert
done/todo label. The button's text always matches a single "next: do X" hint line so the
rail stays honest.

Crucially the live button **navigates and highlights** — it switches to the correct tab and
focuses/pulses the real control (e.g. "Choose workspace →" focuses the workspace field;
"Scan →" switches to the Pipeline tab and pulses the Scan button). It **never auto-runs** a
heavy job (especially a GPU bind). The rail guides; the existing controls still perform. This
keeps the rail decoupled — it targets one control at a time, not a parallel action surface.

Live-button targets by active step: `SETUP` (focus/scroll Setup section), `WORKSPACE` (focus
workspace field / open browse), `SCAN` (Pipeline tab, pulse Scan), `BIND` (Pipeline tab,
pulse Bind), `CURATE` (switch to Library tab).

### Game-not-owned state

If the selected game's install is not configured (`_CHECKS[game](cfg).status is
NOT_CONFIGURED`), the rail does **not** render a broken step sequence. It shows one neutral
line — *"You haven't set up Death Stranding — pick a game you own, or add its path in
Setup"* — never alarm-red. Owning only one of the three games is normal, not a failure. This
reinforces #122 and the optional-vs-required framing.

## Section 2 — Inline guidance pieces

These live on the **existing widgets**, not on the rail.

### 2a — Jargon help-icons

A small reusable `HelpIcon(text)`: a muted ⓘ label with a rich tooltip (and `WhatsThis` for
keyboard access), styled so it never competes visually. Placed next to each jargon term at
its point of use — meaning where the user hits it, not in `docs/BYO.md` they will not open.

| Term | Lives on | Gloss |
|---|---|---|
| BYO | Setup / game-panel pickers | "Bring Your Own — you supply your own legally-owned game files; this app never ships game content." |
| cores | coverage bar / issues panel | short gloss grounded in what the panel counts |
| segments | coverage bar / issues panel | short gloss grounded in what the panel counts |
| cutscene groups | coverage bar / issues panel | short gloss grounded in what the panel counts |
| dupes | issues panel | "duplicate lines the same audio maps to; deduped in export" |
| Main story only (`--main-story`) | its checkbox | tooltip on the control |

One `HelpIcon` class, reused everywhere — one thing to test, consistent look. The exact
one-liners for cores/segments/cutscene-groups are finalized during implementation against
what those panels actually count.

### 2b — Optional-vs-required pills

A reusable `Pill(label, tone)` badge: "Optional" (muted) vs "Needed" (attention). Rendered
on Doctor rows. The Doctor model **already** grades per game (CUDA/ASR are neutral for DS);
this makes that grading *unmissable* by rendering an explicit "Optional for Death Stranding"
pill instead of relying on a `—` glyph/color that reads as absence. A required-but-missing
row gets a "Needed" pill.

Pill and rail reinforce each other: optional extras are visibly labelled **and** never appear
as a blocking rail step.

### 2c — First-run declutter

Wrap Setup and Doctor each in a collapsible section (reusing the `▾/▸` toggle pattern already
in `pipeline.py`'s log console) with a compact one-line header summary:

- **Setup header:** "Tools ready ✓" (collapsed when ready) or "Setup needed — downloads
  ~200 MB" (expanded; this line also serves as the M2 intent banner).
- **Doctor header:** "3 checks OK · 2 optional" (collapsed when all required pass) or
  expanded when a required check is missing.

**Default collapse state is derived from readiness, not remembered:** if required readiness
is met, both start collapsed (the rail carries the status); if a required check is missing or
it is a genuine first run, the relevant section starts expanded, so the detail appears exactly
where the problem is. A healthy returning user sees a compact top; a broken/first-run user
sees the detail.

## Section 3 — File layout, testing, non-goals

### File layout

Follows the repo's established Qt-free-model + thin-view split (same pattern as
`doctor_model`/`setup_model`).

- **New `gui/guide_model.py`** (Qt-free): pure function
  `(doctor_payload, cfg, workspace, game) → JourneySteps`, where each step carries its
  done/current state and the journey carries a `next_action` descriptor (label + target enum
  `SETUP`/`WORKSPACE`/`SCAN`/`BIND`/`CURATE`). All Section 1 completion logic lives here,
  fully unit-testable without Qt.
- **New `gui/views/guide_rail.py`**: the `GuideRail` QWidget — a thin view that renders
  `guide_model` output and emits one `action_requested(target)` signal.
- **New reusable widgets** `HelpIcon` and `Pill` in a new `gui/widgets.py` (or appended to
  `theme.py`), used by Setup/Doctor/coverage/issues/game-panel.
- **Edits:**
  - `shell.py` — insert the rail; map `action_requested` → focus / tab-switch / pulse; add
    the rail to the `_refresh_*` fan-out.
  - `views/setup.py` — collapsible Setup/Doctor sections + summary headers + optional/needed
    pills + BYO help-icon.
  - `views/pipeline_panels.py` — help-icons on the coverage/issues jargon.
  - `views/game_panel.py` — BYO help-icon on the pickers.

### Testing

- `test_guide_model.py` — Qt-free, exhaustive over state permutations: which step is live for
  each readiness combination; the game-not-owned neutral state; Setup-done gating;
  workspace-chosen vs empty.
- Widget tests (pytest-qt, skipping cleanly when Qt/display is absent, per repo convention):
  the rail renders the correct live button; `action_requested` fires the correct target; the
  collapse-default derivation (collapsed when ready, expanded on gap/first-run); the optional
  pill appears on CUDA/ASR rows for DS.

Verify with `./.venv/Scripts/python.exe -m pytest -q` (ruff before pytest, per repo CI gate).

### Non-goals

- No modal wizard / blocking first-run mode (the rail was chosen over that).
- The rail **never auto-runs** heavy jobs — it navigates/focuses only.
- No changes to marker semantics or the CLI; the rail is a read-only reflection of existing
  state.
- `StageStrip` is not reworked.
- Curate has no precise "done" detection — lenient by design.
- Collapse state is **derived from readiness, not persisted** — self-correcting, so a later
  broken state re-expands the relevant section rather than staying hidden behind a remembered
  preference.
