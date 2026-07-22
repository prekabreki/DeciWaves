# CSV order round-trip — design

**Date:** 2026-07-23
**Status:** Approved (brainstorming → design). Next: implementation plan.
**Origin:** New-user dogfooding of the DS narrative-order flow. The auto-derived
story order is "pretty close but jumps around a bit" without a BYO transcript
(see `games/ds/story_order.py`, `engine/transcript_anchor.py`). This feature gives
the user a **manual override**: export the ordered line list, reorder/subset it in
a spreadsheet, and import it back as the definitive reel order.

## Goal

Let a user take the exported line-list CSV, edit it outside the app (reorder rows,
delete rows), and import it back so that **their** row order and membership drive
both the Library display and the rendered reels — with a lossless revert to the
pipeline's automatic story order.

## Core decisions (locked during brainstorming)

1. **The CSV *is* the render list.** Its rows, in that order, become the reels.
   Delete rows to exclude lines; drag rows to reorder. (Order **and** membership.)
2. **Effect scope: Library + export.** After import, the Library re-displays in the
   imported order/membership, and all exports use it. The pipeline's auto-order
   artifact is never mutated, so revert is lossless.
3. **CSV contract: only `line_id` matters.** Row order = play order. Every other
   column is ignored and re-joined from the pipeline's render-input artifact by
   `line_id`. Unknown/duplicate ids are loud errors.
4. **Game scope: all three, DS-first.** The mechanism keys off the game-agnostic
   render-input artifact, so HZD/FW get it for free. DS is the primary, fully
   tested path.

## Architecture & data flow

**Key insight.** The imported order is materialised as a *reordered, subsetted copy
of the render-input artifact* — identical in schema to `playlist.csv`. Therefore
**every existing downstream consumer works unchanged**: Library display, inline
preview, `Export MP3`, and the render stage all already read that schema. No new
"order" concept threads through the pipeline; we add exactly one file and one
load-precedence rule. The thing shown in the Library is byte-for-byte the thing
that renders.

**New GUI-owned artifact:** `out/<game>/gui/imported-order.csv`, alongside the
existing `render-selection.csv` in the GUI namespace.

```
Export order CSV  (exists today as "Export catalog CSV" → writes the story-order artifact)
        │  user edits in a spreadsheet: drag rows to reorder, delete rows to drop
        ▼
Import order CSV ──► validate + join each line_id, in the user's row order, against
                     the current render-input artifact → emit matched full rows
        ▼
out/<game>/gui/imported-order.csv                         ← the override (full schema)
        ▼
library_model.load_lines / export_model.render_input_source
     gain ONE new highest-precedence source: prefer imported-order.csv when present
     (Library order_index = row position ⇒ shows the imported order)
        ▼
Export MP3 → write_render_selection → render-selection.csv → reels in the user's order
```

**Revert:** delete `imported-order.csv`; all consumers fall back to the pipeline's
auto-order artifact. The auto-order file is never touched → revert is lossless.

**Load precedence (both call sites):**
`imported-order.csv` → `playlist.csv` (DS) / `asr-manifest.csv` (HZD) /
`full-reel-manifest.csv` else `subtitle-manifest-full.csv` (FW) → `catalog.csv`.
`library_model.load_lines` and `export_model.render_input_source` both already have
the ordered fallback-chain shape, so each gets a one-line highest-precedence insert.

## Components (Qt-free model / thin widget split, per repo convention)

**`export_model.py`** (Qt-free; all logic + user-facing copy constants; unit-tested
on the base `[test]` install):
- `imported_order_path(workspace, game) -> str` — the override path.
- `has_imported_order(workspace, game) -> bool`.
- `import_order(workspace, game, src_csv) -> ImportResult` — validate + join + write.
  Returns a result carrying success/failure and, on failure, the structured problem
  list (kind, offending ids, row numbers) for the UI to render.
- `revert_imported_order(workspace, game) -> None` — delete the override.
- New highest-precedence branch in `render_input_source`.
- Constants for the inline instructions/gotcha copy.

**`library_model.py`**: `load_lines` gains the same highest-precedence branch so the
Library displays the override.

**`export.py`** (thin widget): new group **"Custom reel order (CSV round-trip)"** in
the Export panel containing the regrouped export button, an import button, a revert
button, the active-override status line, and the inline instructions label. Emits
`import_order_requested(path)` and `revert_order_requested`.

**`shell.py`**: wires the two intents to the model, shows validation results (modal +
log), and calls the existing `_refresh_library()` on success.

## UI, placement & inline instructions

**Home:** the **Export panel** (Library tab), grouped under a heading **"Custom reel
order (CSV round-trip)"**:
- **"Export order CSV…"** — the existing catalog-export button, regrouped (it already
  writes the ordered artifact).
- **"Import order CSV…"** — file dialog; on success writes the override and refreshes
  the Library.
- **"Revert to auto order"** — enabled only when an override is active; deletes it.
- **Active-override status line** (also addresses the "narrative order is invisible"
  finding): override active → *"▶ Showing your imported order (N lines). Reels will
  render in this order."*; otherwise → *"Order: automatic (story order)."*

**Inline instructions / gotchas** (word-wrapped, neutral, selectable — same pattern
as the transcript/`types.json` inline help; copy lives in `export_model`):

> **Custom order — how it works.** Export the CSV, open it in a spreadsheet, then
> **drag rows to reorder** and **delete rows to drop** those lines. Import it back and
> your reels play in that exact order.
> • Only the **`line_id`** column matters — reorder/delete whole rows; don't worry
>   about the other columns.
> • You can reorder or subset **the lines that were exported**; ids that aren't in the
>   current list are rejected on import.
> • Import updates the **Library and future exports** — it does **not** rewrite reels
>   you already rendered. Click **Export MP3** to render in your new order.
> • **Revert to auto order** any time; your imported file is discarded and the app's
>   story order returns.
> • Save as **CSV UTF-8** so accented names survive.

## Validation, errors & edge cases

**Validation is atomic:** nothing is written unless the whole file is valid.

| Problem | Behavior |
|---------|----------|
| No `line_id` column | Reject: "CSV has no `line_id` column — export a fresh copy and keep that column." |
| Unknown `line_id`(s) | Collect **all** offenders; reject with count + first few + row numbers. If *every* id is unknown, add: "none of these ids match `<game>`'s current lines — are you on the right game / did you Scan first?" |
| Duplicate `line_id` | Reject, listing the dupes (a line can't play twice). |
| Empty / all rows deleted | Reject: "no lines to import." |
| Malformed / unreadable CSV | Reject with the parse error. |
| No render-input artifact yet | Import button disabled (nothing to join against — Scan first). |

Errors surface **both** as a concise modal (immediate feedback for a Library-initiated
action) **and** in the log console (consistent with existing export/preview messaging).
Validation lives in the Qt-free `export_model` and is unit-tested without Qt.

**Edge cases & decisions:**
- **Job running:** Import/Revert blocked with "a job is running" (same guard as other
  actions).
- **Re-import:** replaces the active override.
- **Checkbox selection: non-destructive.** Imported rows load with their existing check
  state (the persisted unchecked set carries over by `line_id`); the user can still
  uncheck to trim, and export drops unchecked as usual. Revert keeps prior auto-order
  curation intact. *(Considered and rejected: forcing a clean all-checked slate on
  import, which would discard curation on revert.)*
- **Staleness:** import does **not** auto-render or invalidate `.done-render`. The
  Library updates instantly; already-rendered reels persist until the user clicks
  **Export MP3**. The status line and gotcha bullet communicate this — no intrusive
  long job is started implicitly.

## Testing

**Qt-free model tests** (`tests/gui/test_export_model.py`, base install):
- `import_order` happy path → override has exactly the given ids, in the given order,
  full artifact schema.
- Subset (deleted rows) → override contains only kept ids.
- Reorder (shuffled ids) → override row order matches input row order (load-bearing).
- Rejections, no file written: missing `line_id` column; unknown id(s) + the
  all-unknown "wrong game?" hint; duplicate ids; empty file; malformed CSV.
- Encoding: BOM-tolerant read (`utf-8-sig`), BOM-free write, accented names round-trip.
- `has_imported_order` / `revert_imported_order` deletes the file.
- Precedence: `render_input_source` **and** `library_model.load_lines` prefer the
  override when present (integration lynchpin).
- Round-trip chain (no Qt): export artifact → hand-reorder ids → `import_order` →
  `write_render_selection` reads the override → filtered render-selection reflects the
  imported order.

**Widget tests** (`tests/gui/` view suites):
- Import enabled only with a render-input artifact; Revert enabled only with an
  override.
- `import_order_requested` / `revert_order_requested` fire; status-line text flips
  between "automatic" and "imported (N lines)"; inline help label present + non-empty.

**DS-first:** full-fidelity fixtures + the round-trip chain test target DS; HZD/FW each
get a lighter precedence/parse test confirming the generic path binds to their
render-input artifacts.

## Out of scope (YAGNI)

- Injecting arbitrary catalog lines not produced by story-order (ids absent from the
  render-input artifact simply error — no catalog→playlist schema synthesis).
- Auto-render on import; per-mode selection snapshots; editing order inside the app
  (the spreadsheet is the editor).
- HZD/FW ordering-semantics changes (spine, tiers, gamescript) — untouched.

## Affected files

- `src/deciwaves/gui/export_model.py` (import/revert/precedence + copy) — primary.
- `src/deciwaves/gui/library_model.py` (`load_lines` precedence — one branch).
- `src/deciwaves/gui/export.py` (buttons, status line, inline help, signals).
- `src/deciwaves/gui/shell.py` (wire intents; refresh; surface errors).
- `tests/gui/test_export_model.py` (+ view suite) — tests.
