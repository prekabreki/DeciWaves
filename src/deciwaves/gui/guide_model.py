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

from deciwaves.cli.config import TOOLS
from deciwaves.cli.doctor import Availability
from deciwaves.gui.pipeline_model import has_gpu_stage, scan_target, stage_states

REQUIRED_TOOLS = tuple(t.display for t in TOOLS)


class StepId(Enum):
    SETUP = "setup"
    WORKSPACE = "workspace"
    SCAN = "scan"
    BIND = "bind"
    BUILD = "build"
    CURATE = "curate"
    EXPORT = "export"


class ActionTarget(Enum):
    """What the shell should do when the rail's live button is clicked."""
    SETUP = "setup"
    WORKSPACE = "workspace"
    SCAN = "scan"
    BIND = "bind"
    BUILD = "build"
    CURATE = "curate"


@dataclass(frozen=True)
class Step:
    id: StepId
    label: str
    done: bool
    current: bool  # the single first-not-done step
    running: bool = False  # the step a job is actively working on


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


_EXPORT_DIRS = {
    "ds": "out/audio",
    "hzd": "out/hzd/audio",
    "fw": "out/fw/reels",
}


def _game_out_root(workspace: str, game: str) -> str:
    return os.path.join(workspace, _EXPORT_DIRS.get(game, f"out/{game}"))


def export_done(workspace: str, game: str) -> bool:
    """True iff a rendered ``.mp3`` reel exists in the game's output directory.
    Uses the same per-game mapping as the export job's own success message
    (``job_controller.py``: ds→out/audio, hzd→out/hzd/audio, fw→out/fw/reels).
    A shallow scandir (no deep walk); if reels land elsewhere this under-reports,
    which only leaves the rail nudging toward Library -- a safe, non-blocking
    failure mode."""
    root = _game_out_root(workspace, game)
    try:
        with os.scandir(root) as it:
            if any(e.is_file() and e.name.lower().endswith(".mp3") for e in it):
                return True
    except OSError:
        pass
    return False


_BUILD_HINT = "Run to build your reels"


def build_journey(*, doctor_payload: dict | None, game: str, game_label: str,
                  game_status: Availability, workspace: str,
                  running_step_id: StepId | None = None) -> Journey:
    if game_status is not Availability.OK:
        return Journey(
            game_owned=False, steps=(), next_action=None,
            next_hint=f"You haven't set up {game_label} — "
                      "pick a game you own, or add its path in Setup.")

    ws = workspace or "."
    states = stage_states(game, ws)
    all_done = bool(states) and all(s.done for s in states)
    setup_done = tools_ready(doctor_payload)
    workspace_done = bool((workspace or "").strip())
    exported = export_done(ws, game)

    _library_hint = "Curate & export your reels in the Library tab"

    if has_gpu_stage(game):
        scan_name = scan_target(game)
        scan_done = any(s.name == scan_name and s.done for s in states)
        raw = [
            (StepId.SETUP, "Setup", setup_done, ActionTarget.SETUP,
             "Run setup to download the audio tools"),
            (StepId.WORKSPACE, "Workspace", workspace_done, ActionTarget.WORKSPACE,
             "Choose an output folder for your reels"),
            (StepId.SCAN, "Scan", scan_done, ActionTarget.SCAN,
             "Scan to build the line catalog"),
            (StepId.BIND, "Bind", all_done, ActionTarget.BIND,
             "Bind to attach audio to each line"),
            (StepId.CURATE, "Curate", exported, ActionTarget.CURATE, _library_hint),
            (StepId.EXPORT, "Export", exported, ActionTarget.CURATE, _library_hint),
        ]
    else:
        raw = [
            (StepId.SETUP, "Setup", setup_done, ActionTarget.SETUP,
             "Run setup to download the audio tools"),
            (StepId.WORKSPACE, "Workspace", workspace_done, ActionTarget.WORKSPACE,
             "Choose an output folder for your reels"),
            (StepId.BUILD, "Build", all_done, ActionTarget.BUILD, _BUILD_HINT),
            (StepId.CURATE, "Curate", exported, ActionTarget.CURATE, _library_hint),
            (StepId.EXPORT, "Export", exported, ActionTarget.CURATE, _library_hint),
        ]

    current_idx = next((i for i, r in enumerate(raw) if not r[2]), None)
    steps = tuple(
        Step(sid, label, done, i == current_idx, running=sid == running_step_id)
        for i, (sid, label, done, _a, _h) in enumerate(raw))

    if current_idx is None:
        return Journey(True, steps, None,
                       "All steps done — your reels are in the workspace.")
    action, hint = raw[current_idx][3], raw[current_idx][4]
    running = running_step_id is not None and running_step_id in {s.id for s in steps}
    prefix = "In progress:" if running else "Next:"
    return Journey(True, steps, action, f"{prefix} {hint}")
