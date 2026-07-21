# GUI Onboarding Guide Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a first-time BYO user a state-aware guide rail (Setup → Workspace → Scan → Bind → Curate → Export) with one live "do this next" button, plus inline help-icons, optional/needed pills, and first-run declutter of the Setup/Doctor panels — so they know what to do, in what order, and never mistake an optional/absent extra for a broken install.

**Architecture:** A Qt-free `guide_model` computes the journey (which steps are done, which is the single live step, and the next action) from state the GUI already reads (the `doctor --json` payload, the per-game install `Availability`, the raw workspace string, and `.done-<stage>` markers). A thin `GuideRail` widget renders that journey and emits one `action_requested(ActionTarget)` signal; the shell maps it to a tab-switch + focus. Two reusable widgets (`HelpIcon`, `Pill`) and a `CollapsibleSection` carry the inline pieces. The rail is read-only — it never writes markers or config and never auto-runs a job.

**Tech Stack:** Python 3, PySide6 (Qt6), pytest + pytest-qt. Follows the repo's established Qt-free-model + thin-view split (as in `doctor_model`/`setup_model`).

## Global Constraints

- **Windows-only** project; no cross-platform support.
- **Verify with** `./.venv/Scripts/python.exe -m pytest -q` (the repo `.venv` is the working interpreter; a bare `pytest` may miss the `[test]` extra).
- **Ruff before pytest** — CI gates on lint even when the suite is green. Run `./.venv/Scripts/python.exe -m ruff check .` before every commit.
- **Qt-free models, thin views** — all decision logic lives in a Qt-free module with plain unit tests (no `importorskip`); Qt widgets are thin renderers tested under `tests/gui/` with `pytest.importorskip("PySide6")` and the `qtbot` fixture.
- **Read-only against state** — the guide layer never writes/deletes `.done-*` markers or config; it only reflects existing state.
- **Theme colours come from `deciwaves.gui.theme`** (`OK`, `ERROR`, `WARN`, `NEUTRAL`, `RUNNING`) — never hard-code hex in a widget.
- **Required audio tools** are exactly `("vgmstream", "VGAudio", "ffmpeg")` — the doctor check `name`s (from `config.TOOLS[*].display`).

---

## File Structure

- **Create `src/deciwaves/gui/guide_model.py`** — Qt-free journey computation: `StepId`, `ActionTarget`, `Step`, `Journey`, `tools_ready`, `export_done`, `build_journey`.
- **Create `src/deciwaves/gui/widgets.py`** — reusable `HelpIcon`, `Pill`, `CollapsibleSection`.
- **Create `src/deciwaves/gui/views/guide_rail.py`** — the `GuideRail` thin view.
- **Modify `src/deciwaves/gui/shell.py`** — insert the rail; `_refresh_guide()`; map `action_requested` → tab-switch/focus; add to the refresh fan-out.
- **Modify `src/deciwaves/gui/global_bar.py`** — `current_game_label()`, `focus_workspace()`.
- **Modify `src/deciwaves/gui/views/pipeline_panels.py`** — `PipelineControls.focus_scan()`/`focus_bind()`; `HelpIcon`s on the coverage bar and issues panel.
- **Modify `src/deciwaves/gui/views/setup.py`** — `SetupScreen.focus_run()`; Doctor-row pills; BYO help-icon; wrap Setup/Doctor in `CollapsibleSection` with derived summary + collapse.
- **Modify `src/deciwaves/gui/doctor_model.py`** — `pill_for(item, game)` grading helper.
- **Modify `src/deciwaves/gui/views/game_panel.py`** — BYO help-icon on the transcript/pickers.
- **Tests:** `tests/test_guide_model.py`, `tests/gui/test_guide_rail.py`, `tests/gui/test_shell_guide.py`, `tests/gui/test_widgets.py`, `tests/test_doctor_model.py` (extend), `tests/gui/test_setup_onboarding.py`.

---

## Task 1: `guide_model` — the Qt-free journey

**Files:**
- Create: `src/deciwaves/gui/guide_model.py`
- Test: `tests/test_guide_model.py`

**Interfaces:**
- Consumes: `deciwaves.cli.doctor.Availability`; `deciwaves.gui.pipeline_model.stage_states`, `scan_target`.
- Produces:
  - `REQUIRED_TOOLS: tuple[str, ...]`
  - `class StepId(Enum)` — `SETUP, WORKSPACE, SCAN, BIND, CURATE, EXPORT`
  - `class ActionTarget(Enum)` — `SETUP, WORKSPACE, SCAN, BIND, CURATE`
  - `@dataclass(frozen=True) class Step: id: StepId; label: str; done: bool; current: bool`
  - `@dataclass(frozen=True) class Journey: game_owned: bool; steps: tuple[Step, ...]; next_action: ActionTarget | None; next_hint: str`
  - `tools_ready(payload: dict | None) -> bool`
  - `export_done(workspace: str, game: str) -> bool`
  - `build_journey(*, doctor_payload: dict | None, game: str, game_label: str, game_status: Availability, workspace: str) -> Journey`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guide_model.py
"""Qt-free journey computation for the onboarding guide rail (#112). No importorskip:
the rail's ordering/completion contract is covered on a base install so it can't drift
under a no-[gui] CI run."""
import os

from deciwaves.cli.doctor import Availability
from deciwaves.gui.guide_model import (
    ActionTarget,
    StepId,
    build_journey,
    export_done,
    tools_ready,
)


def _payload(*names_ok):
    """A doctor payload where each name in *names_ok* is an OK check."""
    return {"ok": True, "checks": [
        {"name": n, "ok": True, "status": "ok", "message": "", "fix": ""}
        for n in names_ok]}


_ALL_TOOLS = ("vgmstream", "VGAudio", "ffmpeg")


def _journey(**kw):
    base = dict(doctor_payload=None, game="ds", game_label="Death Stranding",
                game_status=Availability.OK, workspace="")
    base.update(kw)
    return build_journey(**base)


def test_tools_ready_true_only_when_all_three_present():
    assert tools_ready(_payload(*_ALL_TOOLS)) is True
    assert tools_ready(_payload("vgmstream", "VGAudio")) is False
    assert tools_ready(None) is False


def test_not_owned_game_yields_neutral_line_no_steps():
    j = _journey(game_status=Availability.NOT_CONFIGURED)
    assert j.game_owned is False
    assert j.steps == ()
    assert j.next_action is None
    assert "Death Stranding" in j.next_hint


def test_first_step_is_setup_when_nothing_ready():
    j = _journey()
    assert j.next_action is ActionTarget.SETUP
    setup = next(s for s in j.steps if s.id is StepId.SETUP)
    assert setup.current is True and setup.done is False


def test_workspace_is_live_step_once_tools_ready_but_workspace_blank():
    j = _journey(doctor_payload=_payload(*_ALL_TOOLS), workspace="")
    assert j.next_action is ActionTarget.WORKSPACE


def test_scan_is_live_step_once_setup_and_workspace_done(tmp_path):
    j = _journey(doctor_payload=_payload(*_ALL_TOOLS), workspace=str(tmp_path))
    assert j.next_action is ActionTarget.SCAN
    assert "catalog" in j.next_hint.lower()


def test_export_done_detects_mp3_in_reels(tmp_path):
    reels = tmp_path / "out" / "ds" / "reels"
    reels.mkdir(parents=True)
    (reels / "reel_01.mp3").write_bytes(b"x")
    assert export_done(str(tmp_path), "ds") is True
    assert export_done(str(tmp_path), "hzd") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_guide_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'deciwaves.gui.guide_model'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/deciwaves/gui/guide_model.py
"""Qt-free computation of the onboarding "guide rail" journey (#112).

The rail reflects a first-time user's path for the CURRENT (game, workspace):
``Setup -> Workspace -> Scan -> Bind -> Curate -> Export``. Exactly one step is
"live" (the first not-done one); the rail turns that into a single navigate-only
action. Everything is derived from state the GUI already reads -- the
``doctor --json`` payload, the game's install ``Availability``, the raw workspace
string, and the ``.done-<stage>`` markers via :mod:`pipeline_model`. This module
never writes markers or config; it only reads."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from deciwaves.cli.doctor import Availability
from deciwaves.gui.pipeline_model import scan_target, stage_states

# The audio tools setup fetches -- the doctor check `name`s (config.TOOLS[*].display).
REQUIRED_TOOLS = ("vgmstream", "VGAudio", "ffmpeg")


class StepId(Enum):
    SETUP = "setup"
    WORKSPACE = "workspace"
    SCAN = "scan"
    BIND = "bind"
    CURATE = "curate"
    EXPORT = "export"


class ActionTarget(Enum):
    """What the shell should do when the rail's live button is clicked."""
    SETUP = "setup"
    WORKSPACE = "workspace"
    SCAN = "scan"
    BIND = "bind"
    CURATE = "curate"


@dataclass(frozen=True)
class Step:
    id: StepId
    label: str
    done: bool
    current: bool  # the single first-not-done step


@dataclass(frozen=True)
class Journey:
    game_owned: bool
    steps: tuple[Step, ...]          # () when the game isn't owned/configured
    next_action: ActionTarget | None  # None when complete or not owned
    next_hint: str


def tools_ready(payload: dict | None) -> bool:
    """True iff every required audio tool is an OK check in *payload*."""
    if not payload:
        return False
    ok = {c.get("name") for c in payload.get("checks", [])
          if c.get("status") == "ok"}
    return all(t in ok for t in REQUIRED_TOOLS)


def _game_out_root(workspace: str, game: str) -> str:
    # Mirrors export_model._out_dir: DS artifacts live in out/, HZD/FW in out/<game>/.
    return os.path.join(workspace, "out") if game == "ds" \
        else os.path.join(workspace, "out", game)


def export_done(workspace: str, game: str) -> bool:
    """True iff a rendered ``.mp3`` reel exists in the game's out root or its
    ``reels/`` subdir. A shallow scandir (no deep walk); if reels land elsewhere
    this under-reports, which only leaves the rail nudging toward Library -- a
    safe, non-blocking failure mode."""
    root = _game_out_root(workspace, game)
    for d in (root, os.path.join(root, "reels")):
        try:
            with os.scandir(d) as it:
                if any(e.is_file() and e.name.lower().endswith(".mp3") for e in it):
                    return True
        except OSError:
            continue
    return False


def build_journey(*, doctor_payload: dict | None, game: str, game_label: str,
                  game_status: Availability, workspace: str) -> Journey:
    if game_status is not Availability.OK:
        return Journey(
            game_owned=False, steps=(), next_action=None,
            next_hint=f"You haven't set up {game_label} — "
                      "pick a game you own, or add its path in Setup.")

    ws = workspace or "."
    states = stage_states(game, ws)
    scan_name = scan_target(game)
    setup_done = tools_ready(doctor_payload)
    workspace_done = bool((workspace or "").strip())
    scan_done = any(s.name == scan_name and s.done for s in states)
    bind_done = bool(states) and all(s.done for s in states)
    exported = export_done(ws, game)

    _library_hint = "Curate & export your reels in the Library tab"
    # (StepId, label, done, action-when-live, hint-when-live)
    raw = [
        (StepId.SETUP, "Setup", setup_done, ActionTarget.SETUP,
         "Run setup to download the audio tools"),
        (StepId.WORKSPACE, "Workspace", workspace_done, ActionTarget.WORKSPACE,
         "Choose an output folder for your reels"),
        (StepId.SCAN, "Scan", scan_done, ActionTarget.SCAN,
         "Scan to build the line catalog"),
        (StepId.BIND, "Bind", bind_done, ActionTarget.BIND,
         "Bind to attach audio to each line"),
        (StepId.CURATE, "Curate", exported, ActionTarget.CURATE, _library_hint),
        (StepId.EXPORT, "Export", exported, ActionTarget.CURATE, _library_hint),
    ]

    current_idx = next((i for i, r in enumerate(raw) if not r[2]), None)
    steps = tuple(
        Step(sid, label, done, i == current_idx)
        for i, (sid, label, done, _a, _h) in enumerate(raw))

    if current_idx is None:
        return Journey(True, steps, None,
                       "All steps done — your reels are in the workspace.")
    action, hint = raw[current_idx][3], raw[current_idx][4]
    return Journey(True, steps, action, f"Next: {hint}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_guide_model.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui/guide_model.py tests/test_guide_model.py
git add src/deciwaves/gui/guide_model.py tests/test_guide_model.py
git commit -m "feat(gui): guide_model journey computation for onboarding rail (#112)"
```

---

## Task 2: `GuideRail` thin view

**Files:**
- Create: `src/deciwaves/gui/views/guide_rail.py`
- Test: `tests/gui/test_guide_rail.py`

**Interfaces:**
- Consumes: `guide_model.Journey`, `Step`, `ActionTarget`, `build_journey`; `theme.OK`, `theme.NEUTRAL`.
- Produces:
  - `class GuideRail(QWidget)` with signal `action_requested = Signal(object)` (emits an `ActionTarget`), method `set_journey(journey: Journey) -> None`, and `current_action() -> ActionTarget | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_guide_rail.py
"""Thin guide-rail view (#112): renders a guide_model.Journey, exposes the single
live step as a button, and emits action_requested with its ActionTarget. Skips
without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton  # noqa: E402

from deciwaves.cli.doctor import Availability  # noqa: E402
from deciwaves.gui.guide_model import ActionTarget, build_journey  # noqa: E402
from deciwaves.gui.views.guide_rail import GuideRail  # noqa: E402


def _journey(**kw):
    base = dict(doctor_payload=None, game="ds", game_label="Death Stranding",
                game_status=Availability.OK, workspace="")
    base.update(kw)
    return build_journey(**base)


def test_live_step_renders_as_button_and_emits_target(qtbot):
    rail = GuideRail()
    qtbot.addWidget(rail)
    rail.set_journey(_journey())  # SETUP is the live step
    buttons = rail.findChildren(QPushButton)
    assert len(buttons) == 1
    assert buttons[0].text().startswith("Setup")
    with qtbot.waitSignal(rail.action_requested) as blocker:
        buttons[0].click()
    assert blocker.args == [ActionTarget.SETUP]


def test_not_owned_game_shows_hint_no_step_buttons(qtbot):
    rail = GuideRail()
    qtbot.addWidget(rail)
    rail.set_journey(_journey(game_status=Availability.NOT_CONFIGURED))
    assert rail.findChildren(QPushButton) == []
    assert rail.current_action() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_guide_rail.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'deciwaves.gui.views.guide_rail'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/deciwaves/gui/views/guide_rail.py
"""The onboarding guide rail (#112): a slim, always-present strip that renders a
:class:`guide_model.Journey`. Exactly one step -- the live one -- is a button; the
rest are inert done/todo labels. All decision logic is Qt-free in
:mod:`guide_model`; this is the thin renderer + the single ``action_requested``
signal the shell turns into a tab-switch + focus."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from deciwaves.gui.guide_model import ActionTarget, Journey, Step
from deciwaves.gui.theme import NEUTRAL, OK


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class GuideRail(QWidget):
    action_requested = Signal(object)  # emits an ActionTarget

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action: ActionTarget | None = None

        self._steps_row = QHBoxLayout()
        self._steps_row.setContentsMargins(0, 0, 0, 0)
        steps_host = QWidget()
        steps_host.setLayout(self._steps_row)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 2)
        outer.addWidget(steps_host)
        outer.addWidget(self._hint)

    def set_journey(self, journey: Journey) -> None:
        _clear(self._steps_row)
        self._action = journey.next_action
        self._hint.setText(journey.next_hint)
        if not journey.steps:  # game not owned -> hint only
            return
        for i, step in enumerate(journey.steps):
            if i:
                self._steps_row.addWidget(self._separator())
            self._steps_row.addWidget(self._step_widget(step, journey.next_action))
        self._steps_row.addStretch(1)

    def current_action(self) -> ActionTarget | None:
        return self._action

    def _step_widget(self, step: Step, action: ActionTarget | None) -> QWidget:
        if step.current and action is not None:
            btn = QPushButton(f"{step.label} →")
            btn.setToolTip("Take me to the next step")
            btn.clicked.connect(lambda: self.action_requested.emit(action))
            return btn
        mark = "✓" if step.done else "○"
        label = QLabel(f"{mark} {step.label}")
        label.setStyleSheet(f"color: {OK if step.done else NEUTRAL};")
        return label

    def _separator(self) -> QLabel:
        sep = QLabel("›")
        sep.setStyleSheet(f"color: {NEUTRAL};")
        return sep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_guide_rail.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui/views/guide_rail.py tests/gui/test_guide_rail.py
git add src/deciwaves/gui/views/guide_rail.py tests/gui/test_guide_rail.py
git commit -m "feat(gui): GuideRail thin view for the onboarding rail (#112)"
```

---

## Task 3: Wire the rail into the shell (placement, refresh, navigation)

**Files:**
- Modify: `src/deciwaves/gui/global_bar.py` (add `current_game_label()`, `focus_workspace()`)
- Modify: `src/deciwaves/gui/views/pipeline_panels.py` (add `PipelineControls.focus_scan()`, `focus_bind()`)
- Modify: `src/deciwaves/gui/views/setup.py` (add `SetupScreen.focus_run()`)
- Modify: `src/deciwaves/gui/shell.py` (insert rail; `_refresh_guide()`; `_on_guide_action()`; fan-out wiring)
- Test: `tests/gui/test_shell_guide.py`

**Interfaces:**
- Consumes: `GuideRail` (Task 2), `guide_model.build_journey`, `ActionTarget`.
- Produces: `MainWindow.guide: GuideRail`; `MainWindow._refresh_guide()`; `MainWindow._on_guide_action(target)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_shell_guide.py
"""The shell wires the guide rail (#112): it computes the journey from the current
game/workspace/doctor state, and the rail's action navigates (tab-switch/focus)
without running a job. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402

from deciwaves.gui.guide_model import ActionTarget  # noqa: E402
from deciwaves.gui.shell import MainWindow  # noqa: E402


def _win(qtbot, tmp_path):
    settings = QSettings("DeciWavesTest", "gui_guide")
    settings.clear()
    w = MainWindow(settings=settings)
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    return w


def test_curate_action_switches_to_library_tab(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w._on_guide_action(ActionTarget.CURATE)
    assert w.views.currentIndex() == 1  # Library


def test_workspace_action_focuses_workspace_field(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w.show()
    w._on_guide_action(ActionTarget.WORKSPACE)
    assert w.views.currentIndex() == 0  # Pipeline
    assert w.bar._workspace.hasFocus()


def test_refresh_guide_sets_a_journey_hint(qtbot, tmp_path):
    w = _win(qtbot, tmp_path)
    w._refresh_guide()
    assert w.guide._hint.text() != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_shell_guide.py -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'guide'`.

- [ ] **Step 3a: Add the small focus/label helpers**

In `src/deciwaves/gui/global_bar.py`, add these two methods to `GlobalBar` (after `set_workspace`):

```python
    def current_game_label(self) -> str:
        return self._combo.currentText()

    def focus_workspace(self) -> None:
        self._workspace.setFocus()
        self._workspace.selectAll()
```

In `src/deciwaves/gui/views/pipeline_panels.py`, add these two methods to `PipelineControls` (after `set_running`):

```python
    def focus_scan(self) -> None:
        self._scan_btn.setFocus()

    def focus_bind(self) -> None:
        self._bind_btn.setFocus()
```

In `src/deciwaves/gui/views/setup.py`, add this method to `SetupScreen` (after `set_running`):

```python
    def focus_run(self) -> None:
        self._run_btn.setFocus()
```

- [ ] **Step 3b: Insert the rail and its wiring into the shell**

In `src/deciwaves/gui/shell.py`, add the import near the other view imports:

```python
from deciwaves.gui.guide_model import ActionTarget, build_journey
from deciwaves.gui.views.guide_rail import GuideRail
```

In `MainWindow.__init__`, create the rail and add it to the layout between the game panel and the tabs. Replace the layout block:

```python
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.bar)
        layout.addWidget(self.game_panel)
        layout.addWidget(self._tabs)
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)
```

with:

```python
        self.guide = GuideRail()
        self.guide.action_requested.connect(self._on_guide_action)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.bar)
        layout.addWidget(self.game_panel)
        layout.addWidget(self.guide)
        layout.addWidget(self._tabs)
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)
```

Add `_refresh_guide` to the existing fan-out. After the existing `self.bar.game_changed.connect(lambda _g: self._refresh_library())` line, add:

```python
        self.bar.game_changed.connect(lambda _g: self._refresh_guide())
        self.bar.workspace_changed.connect(lambda _ws: self._refresh_guide())
        self.pipeline.setup_doctor.doctor.refreshed.connect(self._refresh_guide)
```

In `_on_pipe_job_finished`, add a `self._refresh_guide()` call alongside the other refreshes:

```python
    def _on_pipe_job_finished(self, code: int) -> None:
        self._poll.stop()
        self._refresh_panels()
        self._refresh_library()
        self._refresh_game_panel()
        self._refresh_guide()
```

In both restore branches at the end of `__init__` (the `if game == "ds":` block and the `else:` block), add `self._refresh_guide()` next to the other prime calls. For the `ds` branch:

```python
            if game == "ds":
                # select_game("ds") leaves the combo on its existing index 0,
                # so game_changed does not fire -- prime explicitly.
                self._refresh_status()
                self._refresh_panels()
                self._refresh_library()
                self._refresh_game_panel()
                self._refresh_guide()
```

For the `else:` branch:

```python
        else:
            cfg = config.load()
            default = _first_owned_game(cfg)
            self.bar.select_game(default)
            self._refresh_status()
            self._refresh_panels()
            self._refresh_library()
            self._refresh_game_panel()
            self._refresh_guide()
```

Add the two new methods (near `_refresh_game_panel`):

```python
    def _refresh_guide(self) -> None:
        """Recompute the onboarding journey for the current game/workspace from the
        install status + last doctor payload, and hand it to the rail (#112)."""
        game = self.bar.current_game()
        cfg = config.load()
        status = _CHECKS[game](cfg).status
        self.guide.set_journey(build_journey(
            doctor_payload=self.pipeline.setup_doctor.doctor.last_payload(),
            game=game,
            game_label=self.bar.current_game_label(),
            game_status=status,
            workspace=self.bar.workspace()))

    def _on_guide_action(self, target) -> None:
        """Navigate to the live step's control -- tab-switch + focus only, never a
        job launch (#112). The user still clicks the real Scan/Bind/etc. button."""
        if target is ActionTarget.CURATE:
            self._tabs.setCurrentIndex(1)  # Library
            return
        self._tabs.setCurrentIndex(0)      # Pipeline for the rest
        if target is ActionTarget.SETUP:
            self.pipeline.setup_doctor.setup.focus_run()
        elif target is ActionTarget.WORKSPACE:
            self.bar.focus_workspace()
        elif target is ActionTarget.SCAN:
            self.pipeline.controls.focus_scan()
        elif target is ActionTarget.BIND:
            self.pipeline.controls.focus_bind()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_shell_guide.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui tests/gui/test_shell_guide.py
git add src/deciwaves/gui/shell.py src/deciwaves/gui/global_bar.py src/deciwaves/gui/views/pipeline_panels.py src/deciwaves/gui/views/setup.py tests/gui/test_shell_guide.py
git commit -m "feat(gui): wire guide rail into shell with navigate-only actions (#112)"
```

---

## Task 4: Reusable `HelpIcon` and `Pill` widgets

**Files:**
- Create: `src/deciwaves/gui/widgets.py`
- Test: `tests/gui/test_widgets.py`

**Interfaces:**
- Consumes: `theme.NEUTRAL`, `theme.WARN`.
- Produces:
  - `class HelpIcon(QLabel)` — `__init__(text: str, parent=None)`; `help_text() -> str`.
  - `class Pill(QLabel)` — `__init__(label: str, tone: str = "optional", parent=None)`; tones `"optional"` (neutral) / `"needed"` (warn).

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_widgets.py
"""Reusable onboarding widgets (#112): a muted ⓘ help-icon carrying a tooltip +
whats-this, and an Optional/Needed pill. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.widgets import HelpIcon, Pill  # noqa: E402


def test_help_icon_carries_text_in_tooltip_and_whatsthis(qtbot):
    icon = HelpIcon("Bring Your Own — you supply your own game files.")
    qtbot.addWidget(icon)
    assert "Bring Your Own" in icon.help_text()
    assert "Bring Your Own" in icon.toolTip()
    assert "Bring Your Own" in icon.whatsThis()


def test_pill_shows_label(qtbot):
    pill = Pill("Optional")
    qtbot.addWidget(pill)
    assert pill.text() == "Optional"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_widgets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'deciwaves.gui.widgets'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/deciwaves/gui/widgets.py
"""Small reusable onboarding widgets (#112), shared across Setup/Doctor/coverage/
issues/game-panel so the look and behaviour are defined and tested once.

- :class:`HelpIcon` -- a muted ⓘ label carrying a rich tooltip + whats-this, for
  expanding jargon at its point of use.
- :class:`Pill` -- a small "Optional"/"Needed" badge that makes the per-game
  optional-vs-required framing unmissable.
- :class:`CollapsibleSection` -- a header (▾/▸ toggle + summary) over a body that
  hides on collapse, for the first-run declutter of the long Setup/Doctor panels."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

from deciwaves.gui.theme import NEUTRAL, WARN


class HelpIcon(QLabel):
    """A muted ⓘ that shows *text* on hover (tooltip) and via What's-This."""

    def __init__(self, text: str, parent=None):
        super().__init__("ⓘ", parent)
        self.setToolTip(text)
        self.setWhatsThis(text)
        self.setStyleSheet(f"color: {NEUTRAL};")
        self.setCursor(Qt.WhatsThisCursor)

    def help_text(self) -> str:
        return self.toolTip()


_PILL_TONES = {"optional": NEUTRAL, "needed": WARN}


class Pill(QLabel):
    """A small rounded badge; *tone* picks the colour (``optional``/``needed``)."""

    def __init__(self, label: str, tone: str = "optional", parent=None):
        super().__init__(label, parent)
        colour = _PILL_TONES.get(tone, NEUTRAL)
        self.setStyleSheet(
            f"color: white; background: {colour}; "
            "border-radius: 6px; padding: 0px 6px;")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_widgets.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui/widgets.py tests/gui/test_widgets.py
git add src/deciwaves/gui/widgets.py tests/gui/test_widgets.py
git commit -m "feat(gui): reusable HelpIcon and Pill widgets (#112)"
```

---

## Task 5: Optional/Needed pills + jargon help-icons on the panels

**Files:**
- Modify: `src/deciwaves/gui/doctor_model.py` (add `pill_for`)
- Modify: `src/deciwaves/gui/views/setup.py` (render pill on Doctor rows; BYO help-icon in Setup header)
- Modify: `src/deciwaves/gui/views/pipeline_panels.py` (help-icons on coverage/issues)
- Modify: `src/deciwaves/gui/views/game_panel.py` (BYO help-icon)
- Test: `tests/test_doctor_model.py` (extend), `tests/gui/test_setup_onboarding.py`

**Interfaces:**
- Consumes: `doctor_model.severity`, `_GPU_READINESS`, `_GPU_GAMES`, `SEV_ERROR`; `widgets.HelpIcon`, `widgets.Pill`.
- Produces: `doctor_model.pill_for(item: DoctorItem, game: str) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing Qt-free test (pill grading)**

Append to `tests/test_doctor_model.py`:

```python
from deciwaves.gui.doctor_model import pill_for


def test_pill_for_cuda_is_optional_on_ds():
    # CUDA absent on DS -> reads as Optional, never a failure (spec §3).
    item = _item("cuda", "unavailable")
    assert pill_for(item, "ds") == ("Optional", "optional")


def test_pill_for_cuda_absent_on_hzd_is_not_optional():
    # On a GPU game CUDA absence is a real readiness gap, not an "Optional" pill.
    item = _item("cuda", "unavailable")
    assert pill_for(item, "hzd") != ("Optional", "optional")


def test_pill_for_broken_required_row_is_needed():
    item = _item("vgmstream", "broken")
    assert pill_for(item, "ds") == ("Needed", "needed")


def test_pill_for_plain_ok_tool_has_no_pill():
    assert pill_for(_item("vgmstream", "ok"), "ds") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_doctor_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'pill_for'`.

- [ ] **Step 3a: Implement `pill_for`**

Append to `src/deciwaves/gui/doctor_model.py`:

```python
def pill_for(item: DoctorItem, game: str) -> tuple[str, str] | None:
    """A ``(label, tone)`` badge for a Doctor row, or None for a plain row.

    Makes the per-game optional-vs-required framing unmissable (#112): the GPU
    extras (CUDA / ASR) read as an explicit "Optional" pill for a non-GPU game
    like DS instead of a bare grey dash, and a genuinely broken required tool
    reads as "Needed"."""
    if item.name in _GPU_READINESS and game not in _GPU_GAMES:
        return ("Optional", "optional")
    if severity(item, game) == SEV_ERROR:
        return ("Needed", "needed")
    return None
```

- [ ] **Step 3b: Render the pill on Doctor rows and add the jargon help-icons**

In `src/deciwaves/gui/views/setup.py`, add to the imports:

```python
from deciwaves.gui.doctor_model import pill_for
from deciwaves.gui.widgets import HelpIcon, Pill
```

and in `DoctorPanel._row_widget`, insert a pill before the final `return row`, right after the `h.addWidget(text_label, 1)` line:

```python
        h.addWidget(text_label, 1)
        pill = pill_for(item, self._game)
        if pill is not None:
            h.addWidget(Pill(*pill))
        return row
```

In `SetupScreen.__init__`, add a BYO help-icon to the Setup header. Replace:

```python
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Setup</b>"))
        header.addStretch(1)
```

with:

```python
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Setup</b>"))
        header.addWidget(HelpIcon(
            "BYO (Bring Your Own): you supply your own legally-owned game files. "
            "Setup only downloads the open-source audio decoders (vgmstream, "
            "VGAudio, ffmpeg) — about 200 MB on first run. This app never ships "
            "game content."))
        header.addStretch(1)
```

In `src/deciwaves/gui/views/pipeline_panels.py`, add the import:

```python
from deciwaves.gui.widgets import HelpIcon
```

In `CoverageBar.__init__`, add a help-icon after `self._label`:

```python
        row.addWidget(self._label)
        row.addWidget(HelpIcon(
            "Coverage: how many voice lines have their audio bound. HZD/FW group "
            "lines into cutscene 'cores' and 'segments'; a sample cap can leave "
            "some groups untranscribed until you 'Transcribe all'."))
        row.addWidget(self._escalate_btn)
```

In `IssuesPanel.__init__`, add a help-icon into the header. Replace:

```python
        self._header = QLabel("<b>Issues</b>")
        self._header.setToolTip("Errors and warnings found during pipeline stages")
        self._body = QWidget()
```

with:

```python
        self._header = QLabel("<b>Issues</b>")
        self._header.setToolTip("Errors and warnings found during pipeline stages")
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self._header)
        header_row.addWidget(HelpIcon(
            "Issues counts per-stage errors and 'dupes' — duplicate lines the same "
            "audio maps to, which are de-duplicated in the exported reels."))
        header_row.addStretch(1)
        self._header_host = QWidget()
        self._header_host.setLayout(header_row)
        self._body = QWidget()
```

and in that same `__init__`, replace `layout.addWidget(self._header)` with `layout.addWidget(self._header_host)`.

In `src/deciwaves/gui/views/game_panel.py`, add the import near the top:

```python
from deciwaves.gui.widgets import HelpIcon
```

and add a BYO help-icon into the transcript row. Replace the existing `transcript_box` construction:

```python
        transcript_box = self._wrap(self._row(
            QLabel("Transcript:"), self._transcript_edit,
            self._transcript_browse, self._reorder_btn))
```

with:

```python
        transcript_box = self._wrap(self._row(
            QLabel("Transcript:"), self._transcript_edit,
            self._transcript_browse, self._reorder_btn,
            HelpIcon(
                "BYO (Bring Your Own): an optional narrative transcript you supply "
                "to improve story ordering. Not required — the app never ships "
                "game text.")))
```

(`_row(*widgets)` is variadic, so appending the `HelpIcon` as a final argument is all that's needed.)

- [ ] **Step 4: Write and run the widget test**

Create `tests/gui/test_setup_onboarding.py`:

```python
"""Onboarding annotations on the Setup/Doctor panels (#112): the Optional pill on
CUDA for DS, and the BYO help-icon in the Setup header. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.views.setup import DoctorPanel, SetupScreen  # noqa: E402
from deciwaves.gui.widgets import HelpIcon, Pill  # noqa: E402

_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}


def test_doctor_renders_optional_pill_for_cuda_on_ds(qtbot):
    panel = DoctorPanel()
    qtbot.addWidget(panel)
    panel.set_game("ds")
    panel.render_payload(_CUDA_ABSENT)
    pills = [p.text() for p in panel.findChildren(Pill)]
    assert "Optional" in pills


def test_doctor_no_optional_pill_for_cuda_on_hzd(qtbot):
    panel = DoctorPanel()
    qtbot.addWidget(panel)
    panel.set_game("hzd")
    panel.render_payload(_CUDA_ABSENT)
    pills = [p.text() for p in panel.findChildren(Pill)]
    assert "Optional" not in pills


def test_setup_header_has_byo_help_icon(qtbot):
    screen = SetupScreen()
    qtbot.addWidget(screen)
    texts = [h.help_text() for h in screen.findChildren(HelpIcon)]
    assert any("Bring Your Own" in t for t in texts)
```

Run: `./.venv/Scripts/python.exe -m pytest tests/test_doctor_model.py tests/gui/test_setup_onboarding.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui tests/test_doctor_model.py tests/gui/test_setup_onboarding.py
git add src/deciwaves/gui/doctor_model.py src/deciwaves/gui/views/setup.py src/deciwaves/gui/views/pipeline_panels.py src/deciwaves/gui/views/game_panel.py tests/test_doctor_model.py tests/gui/test_setup_onboarding.py
git commit -m "feat(gui): optional/needed pills + jargon help-icons (#112)"
```

---

## Task 6: First-run declutter — collapsible Setup/Doctor with derived summaries

**Files:**
- Modify: `src/deciwaves/gui/widgets.py` (add `CollapsibleSection`)
- Modify: `src/deciwaves/gui/views/setup.py` (wrap Setup + Doctor; derive summary + default collapse)
- Test: `tests/gui/test_widgets.py` (extend), `tests/gui/test_setup_onboarding.py` (extend)

**Interfaces:**
- Consumes: `widgets` module; `doctor_model.overall_ok`, `guide_model.tools_ready`.
- Produces:
  - `class CollapsibleSection(QWidget)` — `__init__(title: str, body: QWidget, parent=None)`; `set_summary(text: str)`; `set_collapsed(collapsed: bool)`; `is_collapsed() -> bool`.
  - `SetupDoctorView.apply_readiness_summary()` — derives each section's summary + default collapse from the latest doctor payload.

- [ ] **Step 1: Write the failing test (CollapsibleSection)**

Append to `tests/gui/test_widgets.py`:

```python
from PySide6.QtWidgets import QLabel  # noqa: E402

from deciwaves.gui.widgets import CollapsibleSection  # noqa: E402


def test_collapsible_hides_body_when_collapsed(qtbot):
    body = QLabel("detail")
    section = CollapsibleSection("Setup", body)
    qtbot.addWidget(section)
    section.show()
    section.set_collapsed(True)
    assert section.is_collapsed() is True
    assert body.isVisibleTo(section) is False
    section.set_collapsed(False)
    assert body.isVisibleTo(section) is True


def test_collapsible_shows_summary_text(qtbot):
    section = CollapsibleSection("Doctor", QLabel("rows"))
    qtbot.addWidget(section)
    section.set_summary("3 checks OK · 2 optional")
    assert "3 checks OK" in section.summary_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_widgets.py -q`
Expected: FAIL — `ImportError: cannot import name 'CollapsibleSection'`.

- [ ] **Step 3a: Implement `CollapsibleSection`**

Append to `src/deciwaves/gui/widgets.py` (the `QToolButton`, `QVBoxLayout`, `QWidget` imports are already present in the Task-4 import line; add `QHBoxLayout` and `QLabel` if not already imported — the file already imports `QLabel`, so add `QHBoxLayout`):

Update the import line in `widgets.py` from:

```python
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget
```

to:

```python
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget
```

Then append the class:

```python
class CollapsibleSection(QWidget):
    """A ▾/▸ header (title + optional one-line summary) over a *body* that hides
    when collapsed. Used to declutter the long Setup/Doctor panels on first run:
    a healthy returning user sees a compact summary; a broken/first-run user sees
    the section expanded where the problem is (#112)."""

    def __init__(self, title: str, body: QWidget, parent=None):
        super().__init__(parent)
        self._body = body
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setStyleSheet("border: none;")
        self._title = title
        self._summary = QLabel("")
        self._summary.setStyleSheet(f"color: {NEUTRAL};")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._toggle)
        header.addWidget(self._summary, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(header)
        outer.addWidget(self._body)

        self._toggle.toggled.connect(self._on_toggled)
        self._render_header(expanded=True)

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._render_header(expanded)

    def _render_header(self, expanded: bool) -> None:
        arrow = "▾" if expanded else "▸"
        self._toggle.setText(f"{arrow} {self._title}")

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def summary_text(self) -> str:
        return self._summary.text()

    def set_collapsed(self, collapsed: bool) -> None:
        self._toggle.setChecked(not collapsed)  # fires _on_toggled

    def is_collapsed(self) -> bool:
        return not self._toggle.isChecked()
```

- [ ] **Step 3b: Wrap Setup and Doctor in the shell view, with a derived summary**

In `src/deciwaves/gui/views/setup.py`, extend the imports:

```python
from deciwaves.gui.doctor_model import overall_ok, pill_for
from deciwaves.gui.guide_model import tools_ready
from deciwaves.gui.widgets import CollapsibleSection, HelpIcon, Pill
```

Rewrite `SetupDoctorView` to wrap each panel and derive the summary/collapse on every doctor refresh:

```python
class SetupDoctorView(QFrame):
    """Setup screen above the Doctor panel -- the first-run home (spec §2, §3),
    each wrapped in a CollapsibleSection that collapses once ready (#112)."""

    def __init__(self, base: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setup = SetupScreen(base)
        self.doctor = DoctorPanel(base)
        self.setup_section = CollapsibleSection("Setup", self.setup)
        self.doctor_section = CollapsibleSection("Doctor", self.doctor)

        # first-run flow: a finished setup re-checks doctor toward a green panel (spec §3)
        self.setup.finished.connect(lambda _code: self.doctor.recheck())
        # ...and every doctor result re-grades the setup rows (#110) and re-derives the
        # collapse/summary state (#112).
        self.doctor.refreshed.connect(
            lambda: self.setup.regrade_against_doctor(self.doctor.items()))
        self.doctor.refreshed.connect(self.apply_readiness_summary)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self.setup_section)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)
        layout.addWidget(self.doctor_section)

    def set_game(self, game: str) -> None:
        self.doctor.set_game(game)

    def apply_readiness_summary(self) -> None:
        """Derive each section's one-line summary and default collapse from the
        latest doctor payload: collapse when ready (the rail carries status),
        expand where a required check is missing (#112)."""
        payload = self.doctor.last_payload()
        setup_ok = tools_ready(payload)
        doctor_ok = overall_ok(payload) if payload is not None else False

        self.setup_section.set_summary(
            "Tools ready ✓" if setup_ok else "Setup needed — downloads ~200 MB")
        self.setup_section.set_collapsed(setup_ok)

        items = self.doctor.items()
        total = len(items)
        optional = sum(1 for it in items
                       if pill_for(it, self.doctor._game) == ("Optional", "optional"))
        self.doctor_section.set_summary(
            f"{total - optional} required OK · {optional} optional" if doctor_ok
            else "Doctor found something to fix")
        self.doctor_section.set_collapsed(doctor_ok)
```

- [ ] **Step 4: Write and run the widget test**

Append to `tests/gui/test_setup_onboarding.py`:

```python
from deciwaves.gui.views.setup import SetupDoctorView  # noqa: E402

_ALL_READY = {"ok": True, "checks": [
    {"name": "vgmstream", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "VGAudio", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "ffmpeg", "ok": True, "status": "ok", "message": "", "fix": ""},
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""},
]}
_TOOL_MISSING = {"ok": False, "checks": [
    {"name": "vgmstream", "ok": False, "status": "broken", "message": "", "fix": "run setup"},
]}


def test_sections_collapse_when_ready(qtbot):
    view = SetupDoctorView()
    qtbot.addWidget(view)
    view.doctor.set_game("ds")
    view.doctor.render_payload(_ALL_READY)
    view.apply_readiness_summary()
    assert view.setup_section.is_collapsed() is True
    assert "Tools ready" in view.setup_section.summary_text()


def test_setup_section_expands_when_tool_missing(qtbot):
    view = SetupDoctorView()
    qtbot.addWidget(view)
    view.doctor.set_game("ds")
    view.doctor.render_payload(_TOOL_MISSING)
    view.apply_readiness_summary()
    assert view.setup_section.is_collapsed() is False
    assert "200 MB" in view.setup_section.summary_text()
```

Run: `./.venv/Scripts/python.exe -m pytest tests/gui/test_widgets.py tests/gui/test_setup_onboarding.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src/deciwaves/gui tests/gui/test_widgets.py tests/gui/test_setup_onboarding.py
git add src/deciwaves/gui/widgets.py src/deciwaves/gui/views/setup.py tests/gui/test_widgets.py tests/gui/test_setup_onboarding.py
git commit -m "feat(gui): collapsible Setup/Doctor with derived first-run summary (#112)"
```

---

## Task 7: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass; no new skips beyond the pre-existing real-install/decoder skips.

- [ ] **Step 2: Run ruff over the whole tree**

Run: `./.venv/Scripts/python.exe -m ruff check .`
Expected: no findings.

- [ ] **Step 3: Manual smoke (optional, needs `[gui]`)**

Run: `./.venv/Scripts/python.exe -m deciwaves.gui`
Confirm: the guide rail appears between the global bar and the tabs; with nothing configured it shows "Next: Run setup…" and a live "Setup →" button; clicking it focuses the Run-setup button; switching to a game you don't own shows the neutral "You haven't set up …" line with no step buttons.

- [ ] **Step 4: Commit any lint fixups** (only if Steps 1–2 required changes)

```bash
git add -A
git commit -m "chore(gui): guide-rail suite green + lint clean (#112)"
```

---

## Self-Review

**Spec coverage:**
- Recommended order of operations → Task 1 (`build_journey` ordering) + Task 2/3 (rail renders + navigates). ✓
- Clarify "Workspace" → covered by merged #138 (tooltip/placeholder); the rail additionally makes an unchosen workspace a live "Workspace →" step (Task 1/3). ✓
- Tooltips → merged #138; new jargon help-icons in Task 5. ✓
- Expand jargon inline (BYO, cores, segments, cutscene groups, dupes) → Task 5 help-icons on Setup/coverage/issues/game-panel. ✓
- Frame optional checks as optional, per game → Task 5 `pill_for` + Doctor pills; rail keeps optional extras off the critical path (Task 1 excludes them from steps). ✓
- Declutter first-run screen → Task 6 collapsible Setup/Doctor with derived summary/collapse. ✓
- M2 (silent `.` workspace / intent banner) → Task 1 workspace-chosen step + Task 6 "downloads ~200 MB" summary. ✓
- Game-not-owned neutral state (#122 reinforcement) → Task 1 `game_owned` branch + Task 2 hint-only render. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; test steps show real assertions. The one deferred item in the spec (exact cores/segments/cutscene-group glosses) is resolved to concrete tooltip strings in Task 5. ✓

**Type consistency:** `ActionTarget`/`StepId`/`Step`/`Journey` defined in Task 1 and consumed identically in Tasks 2–3; `pill_for` returns `("Optional","optional")`/`("Needed","needed")` used verbatim in Tasks 5–6; `CollapsibleSection.set_collapsed/is_collapsed/set_summary/summary_text` defined in Task 6 and used consistently in its tests and `apply_readiness_summary`. ✓

## Known heuristics (surface to reviewer)
- **`export_done`** is a shallow `.mp3` check in `out/<game>/` and `out/<game>/reels/`. If a future render writes reels elsewhere it under-reports (rail keeps nudging to Library) — a safe, non-blocking failure mode, not a wrong "done".
- **Curate/Export share one completion signal** (`export_done`): the live action after Bind is always `CURATE` (switch to Library), and `ActionTarget` deliberately has no `EXPORT` member.
