# CSV Order Round-Trip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user export the ordered line list, reorder/subset it in a spreadsheet, and import it back as the definitive reel order (Library display + render), with a lossless revert to auto story order.

**Architecture:** The imported order is materialised as a reordered/subsetted copy of the render-input artifact — identical schema to `playlist.csv` — written to `out/<game>/gui/imported-order.csv`. Two read paths (`export_model.render_input_source`, `library_model.load_lines`) gain the override as highest precedence, so every downstream consumer (Library, preview, Export MP3, render) works unchanged. The importer joins user-supplied `line_id`s (in row order) against the *pipeline* artifact.

**Tech Stack:** Python 3.10+, stdlib `csv`, PySide6, pytest. Windows-only. Repo interpreter: `./.venv/Scripts/python.exe`.

## Global Constraints

- Run tests/lint via `./.venv/Scripts/python.exe -m pytest -q` and `... -m ruff check` (a bare `pytest` may hit a system interpreter). Tests must pass on the base `[test]` install (no Qt needed for model tests).
- Qt-free logic lives in `*_model.py`; `.py` widgets stay thin (repo convention). All user-facing copy constants live in the model module.
- CSV I/O: **read** with `encoding="utf-8-sig"` (BOM-tolerant), **write** BOM-free `utf-8`, atomically via `deciwaves.engine.atomic_io.atomic_write`. Downstream readers (`story_order.read_playlist`) are BOM-intolerant.
- The override file path is `out/<game>/gui/imported-order.csv` for ALL games (GUI namespace, exactly like `render_selection_path`).
- Import is atomic: on ANY validation error, write nothing and return the error list.
- `line_id` is the only required import column; all other columns are re-joined from the pipeline artifact. Row order = play order.
- Non-destructive: import/revert never touch the pipeline's own artifacts or the persisted checkbox selection.
- Match surrounding code style (module docstrings, comment density) in each file you touch.

---

## File structure

- **Modify** `src/deciwaves/gui/export_model.py` — override paths, precedence split, `import_order`, copy constants. (Primary.)
- **Modify** `src/deciwaves/gui/library_model.py` — `_load_ds`/`_load_hzd`/`_load_fw` prefer the override.
- **Modify** `src/deciwaves/gui/export.py` — round-trip UI group, signals, order-state.
- **Modify** `src/deciwaves/gui/job_controller.py` — `start_order_copy` (generalised file-copy worker lives in `export.py`).
- **Modify** `src/deciwaves/gui/shell.py` — wire export/import/revert intents, surface errors, refresh.
- **Modify** `tests/gui/test_export_model.py`, `tests/gui/test_library_model.py`, `tests/gui/test_library_view.py` (or a new `tests/gui/test_export_panel.py`), `tests/gui/test_job_controller.py`.

---

## Task 1: Override path helpers (`export_model`)

**Files:**
- Modify: `src/deciwaves/gui/export_model.py`
- Test: `tests/gui/test_export_model.py`

**Interfaces:**
- Produces: `imported_order_path(workspace: str, game: str) -> str`, `has_imported_order(workspace: str, game: str) -> bool`, `revert_imported_order(workspace: str, game: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_export_model.py
import os
from deciwaves.gui import export_model as em

def test_imported_order_path_is_in_gui_namespace(tmp_path):
    p = em.imported_order_path(str(tmp_path), "ds")
    assert p == os.path.join(str(tmp_path), "out", "ds", "gui", "imported-order.csv")

def test_has_and_revert_imported_order(tmp_path):
    p = em.imported_order_path(str(tmp_path), "ds")
    assert em.has_imported_order(str(tmp_path), "ds") is False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()
    assert em.has_imported_order(str(tmp_path), "ds") is True
    em.revert_imported_order(str(tmp_path), "ds")
    assert em.has_imported_order(str(tmp_path), "ds") is False
    em.revert_imported_order(str(tmp_path), "ds")  # tolerates absence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -k imported_order -q`
Expected: FAIL (`module 'export_model' has no attribute 'imported_order_path'`).

- [ ] **Step 3: Implement the helpers**

Add near `render_selection_path` in `export_model.py`:

```python
def imported_order_path(workspace: str, game: str) -> str:
    """The GUI-owned manual-order override for *game*: ``out/<game>/gui/imported-order.csv``
    (same namespace as :func:`render_selection_path`). When present it is the highest-precedence
    render-input source -- a reordered/subsetted copy of the pipeline's render-input artifact."""
    return os.path.join(workspace, "out", game, "gui", "imported-order.csv")


def has_imported_order(workspace: str, game: str) -> bool:
    """True iff a manual-order override exists for *game*."""
    return os.path.isfile(imported_order_path(workspace, game))


def revert_imported_order(workspace: str, game: str) -> None:
    """Delete *game*'s manual-order override (no-op if absent). Lossless: the pipeline's own
    ordered artifact is never touched, so this restores automatic story order."""
    try:
        os.remove(imported_order_path(workspace, game))
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -k imported_order -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/deciwaves/gui/export_model.py tests/gui/test_export_model.py
git commit -m "feat(gui): imported-order override path helpers"
```

---

## Task 2: Render-input precedence prefers the override (`export_model`)

**Files:**
- Modify: `src/deciwaves/gui/export_model.py:48-69` (the current `render_input_source`)
- Test: `tests/gui/test_export_model.py`

**Interfaces:**
- Consumes: `imported_order_path` (Task 1).
- Produces: `_pipeline_input_source(workspace, game) -> str | None` (the old chain, override-blind); `render_input_source(workspace, game) -> str | None` now returns the override when present, else `_pipeline_input_source`. Import (Task 3) must join against `_pipeline_input_source`, NOT `render_input_source`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_export_model.py
import os
from deciwaves.gui import export_model as em

def _write_csv(path, header="line_id\n", body="a\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(header + body)

def test_render_input_source_prefers_override(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "playlist.csv"))
    # no override yet -> pipeline artifact
    assert em.render_input_source(ws, "ds").endswith(os.path.join("out", "playlist.csv"))
    # override present -> override wins; pipeline resolver still sees playlist
    _write_csv(em.imported_order_path(ws, "ds"))
    assert em.render_input_source(ws, "ds") == em.imported_order_path(ws, "ds")
    assert em._pipeline_input_source(ws, "ds").endswith(os.path.join("out", "playlist.csv"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -k prefers_override -q`
Expected: FAIL (`_pipeline_input_source` undefined / override not preferred).

- [ ] **Step 3: Split the resolver**

Rename the current `render_input_source` body to `_pipeline_input_source` (keep its docstring), then add the override-aware public wrapper. Replace lines 48-69 with:

```python
def _pipeline_input_source(workspace: str, game: str) -> str | None:
    """The pipeline's own render-input CSV (ignoring any manual-order override): DS
    ``out/playlist.csv`` (pre-``order`` -> None), HZD ``out/hzd/asr-manifest.csv`` (pre-``bind``
    -> None), FW ``out/fw/full-reel-manifest.csv`` else ``out/fw/subtitle-manifest-full.csv``
    (pre-``subtitle-bind`` -> None). This is what :func:`import_order` joins against."""
    root = _out_dir(workspace, game)
    if game == "ds":
        candidates = ["playlist.csv"]
    elif game == "hzd":
        candidates = ["asr-manifest.csv"]
    elif game == "fw":
        candidates = ["full-reel-manifest.csv", "subtitle-manifest-full.csv"]
    else:
        return None
    for name in candidates:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None


def render_input_source(workspace: str, game: str) -> str | None:
    """The render-input CSV the render stage reads, override-aware: a manual-order override
    (:func:`imported_order_path`) wins when present, else the pipeline artifact
    (:func:`_pipeline_input_source`). All consumers (Export MP3, the Library) go through this,
    so an active override drives both display and render."""
    override = imported_order_path(workspace, game)
    if os.path.isfile(override):
        return override
    return _pipeline_input_source(workspace, game)
```

- [ ] **Step 4: Run test to verify it passes; run the whole export-model suite for regressions**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -q`
Expected: PASS (existing `can_export_mp3` / `write_render_selection` tests still green — they call `render_input_source`, whose no-override behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/deciwaves/gui/export_model.py tests/gui/test_export_model.py
git commit -m "feat(gui): render_input_source prefers manual-order override"
```

---

## Task 3: `import_order` — validate, join, write (`export_model`)

**Files:**
- Modify: `src/deciwaves/gui/export_model.py`
- Test: `tests/gui/test_export_model.py`

**Interfaces:**
- Consumes: `_pipeline_input_source`, `imported_order_path`, `atomic_write`, `_missing_source_message`.
- Produces: `@dataclass(frozen=True) ImportResult(ok: bool, path: str | None, count: int, errors: list[str])`; `import_order(workspace: str, game: str, src_csv: str) -> ImportResult`; `ROUND_TRIP_INSTRUCTIONS: str` (UI copy consumed by Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/gui/test_export_model.py
import os, csv
from deciwaves.gui import export_model as em

def _write_playlist(ws, ids):
    p = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "subtitle", "stream_path"])
        w.writeheader()
        for i in ids:
            w.writerow({"line_id": i, "subtitle": f"sub {i}", "stream_path": f"{i}.stream"})

def _write_user_csv(path, rows, header="line_id,note\n"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(header)
        for r in rows:
            f.write(r + "\n")

def test_import_order_happy_reorders_and_subsets(tmp_path):
    ws = str(tmp_path)
    _write_playlist(ws, ["a", "b", "c", "d"])
    src = os.path.join(ws, "edited.csv")
    _write_user_csv(src, ["c,x", "a,y"])  # subset + reorder
    res = em.import_order(ws, "ds", src)
    assert res.ok and res.count == 2 and not res.errors
    with open(em.imported_order_path(ws, "ds"), encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert [r["line_id"] for r in rows] == ["c", "a"]           # user's order
    assert rows[0]["subtitle"] == "sub c"                        # re-joined from playlist
    assert list(rows[0].keys()) == ["line_id", "subtitle", "stream_path"]  # base schema

def test_import_order_missing_line_id_column(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["a"])
    src = os.path.join(ws, "e.csv"); _write_user_csv(src, ["a"], header="id,note\n")
    res = em.import_order(ws, "ds", src)
    assert not res.ok and not em.has_imported_order(ws, "ds")
    assert "line_id" in res.errors[0]

def test_import_order_unknown_ids_all_unknown_hint(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["a", "b"])
    src = os.path.join(ws, "e.csv"); _write_user_csv(src, ["x", "y"])
    res = em.import_order(ws, "ds", src)
    assert not res.ok and not em.has_imported_order(ws, "ds")
    joined = " ".join(res.errors)
    assert "not in" in joined and "right game" in joined  # all-unknown hint

def test_import_order_duplicate_ids(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["a", "b"])
    src = os.path.join(ws, "e.csv"); _write_user_csv(src, ["a", "a"])
    res = em.import_order(ws, "ds", src)
    assert not res.ok and any("duplicate" in e for e in res.errors)

def test_import_order_empty(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["a"])
    src = os.path.join(ws, "e.csv"); _write_user_csv(src, [])
    res = em.import_order(ws, "ds", src)
    assert not res.ok and any("no lines" in e for e in res.errors)

def test_import_order_no_pipeline_artifact(tmp_path):
    res = em.import_order(str(tmp_path), "ds", os.path.join(str(tmp_path), "e.csv"))
    assert not res.ok and res.errors

def test_import_order_bom_and_accents(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["é1", "é2"])
    src = os.path.join(ws, "e.csv")
    with open(src, "w", newline="", encoding="utf-8-sig") as f:  # BOM + accents
        f.write("line_id\né2\né1\n")
    res = em.import_order(ws, "ds", src)
    assert res.ok
    with open(em.imported_order_path(ws, "ds"), "rb") as f:
        head = f.read(3)
    assert head != b"\xef\xbb\xbf"  # BOM-free write
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -k import_order -q`
Expected: FAIL (`import_order` undefined).

- [ ] **Step 3: Implement `ImportResult`, `import_order`, and the copy constant**

Add `from dataclasses import dataclass` to the imports if absent. Add:

```python
ROUND_TRIP_INSTRUCTIONS = (
    "Custom order — how it works. Export the CSV, open it in a spreadsheet, then drag "
    "rows to reorder and delete rows to drop those lines. Import it back and your reels "
    "play in that exact order.\n"
    "• Only the line_id column matters — reorder/delete whole rows; don't worry about the "
    "other columns.\n"
    "• You can reorder or subset the lines that were exported; ids that aren't in the "
    "current list are rejected on import.\n"
    "• Import updates the Library and future exports — it does not rewrite reels you already "
    "rendered. Click Export MP3 to render in your new order.\n"
    "• Revert to auto order any time; your imported file is discarded and the app's story "
    "order returns.\n"
    "• Save as CSV UTF-8 so accented names survive."
)


@dataclass(frozen=True)
class ImportResult:
    """Outcome of :func:`import_order`. ``ok`` True -> ``path`` is the written override and
    ``count`` its row count; ``ok`` False -> ``errors`` holds one friendly line per problem
    and nothing was written (atomic)."""
    ok: bool
    path: str | None
    count: int
    errors: list[str]


def import_order(workspace: str, game: str, src_csv: str) -> ImportResult:
    """Turn a user-edited CSV into a manual-order override. Row order = play order; the only
    required column is ``line_id`` (others are re-joined from the pipeline artifact). Validates
    atomically -- unknown ids, duplicate ids, a missing ``line_id`` column, an empty file, or a
    missing pipeline artifact all abort with nothing written. On success writes
    :func:`imported_order_path` (base schema, base row data, the user's order)."""
    base_src = _pipeline_input_source(workspace, game)
    if base_src is None:
        return ImportResult(False, None, 0, [_missing_source_message(game)])

    with open(base_src, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        by_id = {r.get("line_id", ""): r for r in reader if r.get("line_id", "")}

    try:
        with open(src_csv, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if "line_id" not in (reader.fieldnames or []):
                return ImportResult(False, None, 0, [
                    "CSV has no 'line_id' column -- export a fresh copy and keep that column."])
            # enumerate from 2: row 1 is the header, so row numbers match the spreadsheet
            ordered = [((r.get("line_id") or "").strip(), n)
                       for n, r in enumerate(reader, start=2)]
    except OSError as exc:
        return ImportResult(False, None, 0, [f"Could not read CSV: {exc}"])

    ordered = [(lid, n) for lid, n in ordered if lid]  # drop blank-id rows (trailing lines)
    if not ordered:
        return ImportResult(False, None, 0, [
            "no lines to import (the file has no line_id values)."])

    errors: list[str] = []
    seen: dict[str, int] = {}
    unknown: list[tuple[str, int]] = []
    dupes: list[tuple[str, int]] = []
    for lid, n in ordered:
        if lid in seen:
            dupes.append((lid, n))
        else:
            seen[lid] = n
            if lid not in by_id:
                unknown.append((lid, n))

    if unknown:
        sample = ", ".join(f"{lid} (row {n})" for lid, n in unknown[:5])
        msg = f"{len(unknown)} line_id(s) not in {game}'s current lines: {sample}"
        if len(unknown) == len(seen):  # every distinct id is unknown
            msg += " -- none match; are you on the right game, and did you Scan first?"
        errors.append(msg)
    if dupes:
        sample = ", ".join(f"{lid} (row {n})" for lid, n in dupes[:5])
        errors.append(f"{len(dupes)} duplicate line_id(s) (a line can't play twice): {sample}")
    if errors:
        return ImportResult(False, None, 0, errors)

    out_path = imported_order_path(workspace, game)
    rows = [by_id[lid] for lid, _ in ordered]

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    atomic_write(out_path, _write)
    return ImportResult(True, out_path, len(rows), [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_model.py -k import_order -q`
Expected: PASS (all import_order cases).

- [ ] **Step 5: Commit**

```bash
git add src/deciwaves/gui/export_model.py tests/gui/test_export_model.py
git commit -m "feat(gui): import_order validates+joins a user CSV into an order override"
```

---

## Task 4: Library loaders prefer the override (`library_model`)

**Files:**
- Modify: `src/deciwaves/gui/library_model.py:117-130` (`_load_ds`), plus the analogous heads of `_load_hzd` and `_load_fw`.
- Test: `tests/gui/test_library_model.py`

**Interfaces:**
- Consumes: `export_model.imported_order_path` (Task 1). Add `from deciwaves.gui.export_model import imported_order_path` (no import cycle: `export_model` does not import `library_model`).
- Produces: `load_lines` returns override rows in override row order (`order_index` = position) when an override exists.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_library_model.py
import os, csv
from deciwaves.gui import library_model as lm
from deciwaves.gui.export_model import imported_order_path

def _write_playlist(ws, ids):
    p = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "subtitle", "speaker",
                                          "scene", "category", "stream_path"])
        w.writeheader()
        for i in ids:
            w.writerow({"line_id": i, "subtitle": f"s{i}", "speaker": "", "scene": "",
                        "category": "", "stream_path": f"{i}.stream"})

def test_ds_load_prefers_override_in_its_order(tmp_path):
    ws = str(tmp_path)
    _write_playlist(ws, ["a", "b", "c"])
    # override = playlist-shaped, reordered subset
    ov = imported_order_path(ws, "ds")
    os.makedirs(os.path.dirname(ov), exist_ok=True)
    with open(ov, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "subtitle", "speaker",
                                          "scene", "category", "stream_path"])
        w.writeheader()
        for i in ["c", "a"]:
            w.writerow({"line_id": i, "subtitle": f"s{i}", "speaker": "", "scene": "",
                        "category": "", "stream_path": f"{i}.stream"})
    rows = lm.load_lines(ws, "ds")
    assert [r.line_id for r in rows] == ["c", "a"]
    assert [r.order_index for r in rows] == [0, 1]

def test_ds_load_falls_back_to_playlist_without_override(tmp_path):
    ws = str(tmp_path); _write_playlist(ws, ["a", "b", "c"])
    rows = lm.load_lines(ws, "ds")
    assert [r.line_id for r in rows] == ["a", "b", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_library_model.py -k override -q`
Expected: FAIL (override ignored; order is `a,b,c`).

- [ ] **Step 3: Prefer the override in `_load_ds`**

Add the import at the top of `library_model.py`:

```python
from deciwaves.gui.export_model import imported_order_path
```

Replace `_load_ds` (lines 117-130) with:

```python
def _load_ds(workspace: str) -> list[LineRow]:
    root = _out_dir(workspace, "ds")
    # A manual-order override (out/ds/gui/imported-order.csv) is playlist-shaped, so it reads
    # through the same mapping and simply substitutes for playlist.csv when present (#round-trip).
    override = imported_order_path(workspace, "ds")
    src = override if os.path.isfile(override) else os.path.join(root, "playlist.csv")
    if os.path.isfile(src):
        out = []
        for i, r in enumerate(_read_csv(src)):
            sub = r.get("subtitle")
            out.append(LineRow(
                line_id=r.get("line_id", ""), speaker=r.get("speaker") or None,
                subtitle=sub, scene=r.get("scene") or None, category=r.get("category") or None,
                audio_path=r.get("stream_path") or None, has_subtitle=_has_subtitle(sub),
                order_index=i))
        return out
    return _load_ds_catalog_shape(os.path.join(root, "catalog.csv"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_library_model.py -k override -q`
Expected: PASS.

- [ ] **Step 5: Apply the analogous change to HZD and FW (lighter)**

In `_load_hzd`, before it resolves `asr-manifest.csv`, substitute the override when present (the HZD override is asr-manifest-shaped, so the existing manifest-branch mapping applies unchanged). In `_load_fw`, substitute the override for the `full-reel-manifest.csv`/`subtitle-manifest-full.csv` choice the same way. Pattern for each: `src = override if os.path.isfile(override) else <existing story-order path>`, feeding the existing manifest-branch mapping; keep the catalog/clip-index fallback untouched. Add one precedence test per game mirroring `test_ds_load_prefers_override_in_its_order` (write a manifest-shaped override, assert row order).

- [ ] **Step 6: Run the full library-model suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_library_model.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/deciwaves/gui/library_model.py tests/gui/test_library_model.py
git commit -m "feat(gui): Library loaders prefer the manual-order override"
```

---

## Task 5: Export panel round-trip UI (`export.py`)

**Files:**
- Modify: `src/deciwaves/gui/export.py`
- Test: `tests/gui/test_export_panel.py` (new; or extend `tests/gui/test_library_view.py`)

**Interfaces:**
- Consumes: `export_model.ROUND_TRIP_INSTRUCTIONS`.
- Produces (on `ExportPanel`): signals `export_order_requested(str)`, `import_order_requested(str)`, `revert_order_requested()`; `set_context(...)` gains keyword args `order_active: bool = False, order_count: int = 0`; accessors `export_order_enabled() -> bool`, `import_enabled() -> bool`, `revert_enabled() -> bool`, `order_status_text() -> str`.

- [ ] **Step 1: Write the failing widget test**

```python
# tests/gui/test_export_panel.py
import pytest
from deciwaves.gui.export import ExportPanel

@pytest.fixture
def panel(qtbot):
    p = ExportPanel(); qtbot.addWidget(p); return p

def test_round_trip_enable_and_status(panel):
    # override inactive, artifact present, rows checked, not running
    panel.set_context("ds", ".", checked_count=3, can_mp3=True, can_catalog=True,
                      order_active=False, order_count=0)
    assert panel.export_order_enabled() is True
    assert panel.import_enabled() is True
    assert panel.revert_enabled() is False
    assert "automatic" in panel.order_status_text().lower()
    # override active
    panel.set_context("ds", ".", checked_count=3, can_mp3=True, can_catalog=True,
                      order_active=True, order_count=42)
    assert panel.revert_enabled() is True
    assert "42" in panel.order_status_text()

def test_round_trip_signals(panel, qtbot, tmp_path, monkeypatch):
    panel.set_context("ds", str(tmp_path), 3, True, True, order_active=True, order_count=1)
    from deciwaves.gui import export as ex
    monkeypatch.setattr(ex.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "e.csv"), "")))
    with qtbot.waitSignal(panel.import_order_requested):
        panel._on_import_clicked()
    with qtbot.waitSignal(panel.revert_order_requested):
        panel._revert_btn.click()

def test_instructions_present(panel):
    assert panel._instructions.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_panel.py -q`
Expected: FAIL (attributes/signals missing).

- [ ] **Step 3: Add the round-trip group to `ExportPanel`**

Add imports at top of `export.py`: `from deciwaves.gui.export_model import catalog_source_path, ROUND_TRIP_INSTRUCTIONS` and (for the neutral help colour) `from deciwaves.gui.theme import NEUTRAL`. Add signals under the existing ones:

```python
    export_order_requested = Signal(str)   # chosen dest file (writes the ordered artifact)
    import_order_requested = Signal(str)    # chosen source file (the user's edited CSV)
    revert_order_requested = Signal()       # discard the override, back to auto order
```

In `__init__`, add state `self._order_active = False; self._order_count = 0`, build the widgets, and lay them out below `row2`:

```python
        self._order_export_btn = QPushButton("Export order CSV…")
        self._order_import_btn = QPushButton("Import order CSV…")
        self._order_revert_btn = QPushButton("Revert to auto order")
        self._order_status = QLabel("")
        self._order_status.setWordWrap(True)
        self._instructions = QLabel(ROUND_TRIP_INSTRUCTIONS)
        self._instructions.setWordWrap(True)
        self._instructions.setStyleSheet(f"color: {NEUTRAL};")
        self._instructions.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        order_hdr = QLabel("<b>Custom reel order (CSV round-trip)</b>")
        order_row = QHBoxLayout()
        order_row.addWidget(self._order_export_btn)
        order_row.addWidget(self._order_import_btn)
        order_row.addWidget(self._order_revert_btn)
        order_row.addStretch(1)
        # (append after the existing `layout.addWidget(self._status)`)
        layout.addWidget(order_hdr)
        layout.addLayout(order_row)
        layout.addWidget(self._order_status)
        layout.addWidget(self._instructions)

        self._order_export_btn.clicked.connect(self._on_order_export_clicked)
        self._order_import_btn.clicked.connect(self._on_import_clicked)
        self._order_revert_btn.clicked.connect(self.revert_order_requested)
```

Add `Qt` to the `PySide6.QtCore` import line (`from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot`).

Extend `set_context` signature and body:

```python
    def set_context(self, game: str, workspace: str, checked_count: int,
                    can_mp3: bool, can_catalog: bool,
                    order_active: bool = False, order_count: int = 0) -> None:
        ...  # existing body unchanged, then:
        self._order_active = order_active
        self._order_count = order_count
        self._update()
```

Extend `_update` (append):

```python
        artifact = self._can_mp3  # render-input artifact exists (same gate as Export MP3)
        self._order_export_btn.setEnabled(artifact and can_start)
        self._order_import_btn.setEnabled(artifact and not self._running and has_workspace)
        self._order_revert_btn.setEnabled(
            self._order_active and not self._running and has_workspace)
        if self._order_active:
            self._order_status.setText(
                f"▶ Showing your imported order ({self._order_count:,} lines). "
                "Reels will render in this order.")
        else:
            self._order_status.setText("Order: automatic (story order).")
```

Add intent handlers and accessors:

```python
    def _on_order_export_clicked(self) -> None:
        default = os.path.join(self._workspace, f"{self._game or 'order'}-order.csv")
        path, _f = QFileDialog.getSaveFileName(self, "Export order CSV", default,
                                               "CSV files (*.csv)")
        if path:
            self.export_order_requested.emit(path)

    def _on_import_clicked(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "Import order CSV", self._workspace,
                                               "CSV files (*.csv);;All files (*.*)")
        if path:
            self.import_order_requested.emit(path)

    def export_order_enabled(self) -> bool:
        return self._order_export_btn.isEnabled()

    def import_enabled(self) -> bool:
        return self._order_import_btn.isEnabled()

    def revert_enabled(self) -> bool:
        return self._order_revert_btn.isEnabled()

    def order_status_text(self) -> str:
        return self._order_status.text()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_export_panel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/deciwaves/gui/export.py tests/gui/test_export_panel.py
git commit -m "feat(gui): export panel round-trip controls + inline instructions"
```

---

## Task 6: `start_order_copy` (`job_controller` + generalised copy worker)

**Files:**
- Modify: `src/deciwaves/gui/export.py` (generalise the copy worker)
- Modify: `src/deciwaves/gui/job_controller.py:151-160` (`start_catalog_copy` area)
- Test: `tests/gui/test_job_controller.py`

**Interfaces:**
- Consumes: `export_model.render_input_source`.
- Produces: `JobController.start_order_copy(game: str, workspace: str, dest: str) -> None` (mirrors `start_catalog_copy`), emitting the same `dump_status`/log path the catalog copy uses.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_job_controller.py  (follow the file's existing worker-copy test pattern)
import os, csv
from deciwaves.gui.export import _CatalogCopyWorker, _CatalogCopySignals

def test_order_copy_worker_copies_render_input(tmp_path, qtbot):
    ws = str(tmp_path)
    p = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["line_id"], ["a"]])
    dest = os.path.join(ws, "exported-order.csv")
    sig = _CatalogCopySignals()
    worker = _CatalogCopyWorker(ws, "ds", dest, sig, kind="order")
    worker.run()
    assert os.path.isfile(dest)
    with open(dest, encoding="utf-8-sig") as f:
        assert "line_id" in f.read()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_job_controller.py -k order_copy -q`
Expected: FAIL (`_CatalogCopyWorker` has no `kind` param).

- [ ] **Step 3: Generalise the copy worker source**

In `export.py`, add the import `render_input_source` to the existing `from deciwaves.gui.export_model import ...` line, and change `_CatalogCopyWorker` to select its source by `kind`:

```python
    def __init__(self, game, workspace, dest, signals, kind: str = "catalog"):
        super().__init__()
        self._game = game
        self._workspace = workspace
        self._dest = dest
        self._signals = signals
        self._kind = kind

    @Slot()
    def run(self) -> None:
        src = (render_input_source if self._kind == "order"
               else catalog_source_path)(self._workspace, self._game)
        noun = "order CSV" if self._kind == "order" else "catalog"
        if src is None:
            self._signals.finished.emit(f"export: no {noun} artifact yet for this game.\n")
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._dest)), exist_ok=True)
            shutil.copyfile(src, self._dest)
            self._signals.finished.emit(f"export: {noun} copied to {self._dest}\n")
        except OSError as exc:
            self._signals.finished.emit(f"export: could not write {noun}: {exc}\n")
```

- [ ] **Step 4: Add `start_order_copy` to `JobController`**

Locate `start_catalog_copy` (job_controller.py:151) and add a sibling right after it (reusing `_CatalogCopyWorker` with `kind="order"` and the same signals/`_on_catalog_copy_finished` handler):

```python
    def start_order_copy(self, game: str, workspace: str, dest: str) -> None:
        from deciwaves.gui.export import _CatalogCopyWorker, _CatalogCopySignals
        signals = _CatalogCopySignals()
        signals.finished.connect(self._on_catalog_copy_finished)
        worker = _CatalogCopyWorker(game, workspace, dest, signals, kind="order")
        self._catalog_signals = signals
        self._pool.start(worker)
```

(Match how `start_catalog_copy` obtains its pool/imports — mirror it exactly, only adding `kind="order"`.)

- [ ] **Step 5: Run tests to verify pass (incl. existing catalog-copy test)**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_job_controller.py -q`
Expected: PASS (order copy works; existing catalog copy still green — default `kind="catalog"`).

- [ ] **Step 6: Commit**

```bash
git add src/deciwaves/gui/export.py src/deciwaves/gui/job_controller.py tests/gui/test_job_controller.py
git commit -m "feat(gui): start_order_copy exports the ordered render-input artifact"
```

---

## Task 7: Wire intents in the shell (`shell.py`)

**Files:**
- Modify: `src/deciwaves/gui/shell.py` (export wiring block ~lines 90-93; `_on_export_catalog` area; the Library refresh path)
- Modify: `src/deciwaves/gui/views/library.py` (pass order-state into `export.set_context`)
- Test: manual (documented below) + the existing shell/library suites must stay green.

**Interfaces:**
- Consumes: `export_model.import_order`, `export_model.has_imported_order`, `export_model.revert_imported_order`, `JobController.start_order_copy` (Task 6), `ExportPanel` signals (Task 5).

- [ ] **Step 1: Pass order-state into the export panel from the Library**

In `library.py`, find where `self.export.set_context(...)` is called during `refresh`/`_update_export_context` and add the override state. Add an import `from deciwaves.gui.export_model import has_imported_order`, and pass:

```python
        order_active = has_imported_order(self._workspace, self._game) if self._game else False
        self.export.set_context(self._game, self._workspace, self._checked_count,
                                self._can_export_mp3, self._can_catalog,
                                order_active=order_active,
                                order_count=len(self._rows) if order_active else 0)
```

(`len(self._rows)` is the loaded row count, which — when an override is active — is the override's row count, exactly what the status line reports.)

- [ ] **Step 2: Wire the three export-panel intents in the shell**

In `MainWindow.__init__`, next to the existing `self.library.export.export_catalog_requested.connect(...)` line, add:

```python
        self.library.export.export_order_requested.connect(self._on_export_order)
        self.library.export.import_order_requested.connect(self._on_import_order)
        self.library.export.revert_order_requested.connect(self._on_revert_order)
```

Add the handlers (near `_on_export_catalog`):

```python
    def _on_export_order(self, dest: str) -> None:
        if not self._has_workspace():
            return
        self._controller.start_order_copy(
            self.bar.current_game(), self._workspace(), dest)

    def _on_import_order(self, src: str) -> None:
        if not self._has_workspace():
            return
        from PySide6.QtWidgets import QMessageBox

        from deciwaves.gui.export_model import import_order
        result = import_order(self._workspace(), self.bar.current_game(), src)
        if not result.ok:
            self.pipeline.append_log(
                "import order failed:\n  " + "\n  ".join(result.errors) + "\n")
            QMessageBox.warning(self, "Import order", "\n".join(result.errors))
            return
        self.pipeline.append_log(
            f"import order: {result.count} line(s) -> your custom order is now active. "
            "Click Export MP3 to render in this order.\n")
        self._refresh_library()

    def _on_revert_order(self) -> None:
        if not self._has_workspace():
            return
        from deciwaves.gui.export_model import revert_imported_order
        revert_imported_order(self._workspace(), self.bar.current_game())
        self.pipeline.append_log("reverted to automatic story order.\n")
        self._refresh_library()
```

(Model functions are `(workspace, game, ...)` — the calls above use that order.)

- [ ] **Step 3: Verify existing suites stay green**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/ -q`
Expected: PASS (521+ tests; the widened `set_context` uses defaults so any untouched caller still compiles, and the new callers pass the keywords).

- [ ] **Step 4: Lint the whole GUI package**

Run: `./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui/`
Expected: `All checks passed!`

- [ ] **Step 5: Manual end-to-end verification (documented)**

With a completed DS workspace (`out/playlist.csv` present), launch the GUI, go to Library → Export panel:
1. Click **Export order CSV…**, save it; confirm the file has the playlist rows in story order.
2. In a spreadsheet, delete some rows and reorder others; save as CSV UTF-8.
3. Click **Import order CSV…**, pick it. Confirm: status line flips to "▶ Showing your imported order (N lines)", the Library list reorders/subsets to match, and Revert becomes enabled.
4. Click **Export MP3**; confirm reels render in the imported order.
5. Click **Revert to auto order**; confirm the Library returns to story order and status reads "automatic".
6. Import a CSV with a bad id / no `line_id` column; confirm the warning dialog + log line and that no override is written.

- [ ] **Step 6: Commit**

```bash
git add src/deciwaves/gui/shell.py src/deciwaves/gui/views/library.py
git commit -m "feat(gui): wire CSV order round-trip (export/import/revert) in the shell"
```

---

## Self-review notes (already reconciled)

- **Spec coverage:** override artifact + precedence (Tasks 1–2, 4), import/validate/join (Task 3), UI + inline instructions (Task 5), export-of-ordered-artifact (Task 6), wiring + errors + refresh + revert (Task 7). All-games: DS is coded in full; HZD/FW get the analogous loader change + a test each (Task 4, Step 5). Non-destructive checkbox (never modifies selection) and no-auto-render (import only refreshes the Library; user clicks Export MP3) are honored — no task touches selection persistence or `.done-render`.
- **Join source:** import joins against `_pipeline_input_source` (override-blind), so a prior override never narrows what can be re-imported (Task 3). Export-of-order uses `render_input_source` (override-aware) so re-export reflects the current effective order.
- **Type consistency:** `ImportResult(ok, path, count, errors)`, `import_order(workspace, game, src_csv)`, `set_context(..., order_active=False, order_count=0)`, `start_order_copy(game, workspace, dest)`, `_CatalogCopyWorker(..., kind="catalog")` are used identically wherever referenced. The shell arg-order correction is called out explicitly in Task 7 Step 2.
