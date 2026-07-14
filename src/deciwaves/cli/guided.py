"""``deciwaves`` with no subcommand: a thin guided interactive flow (Task 17).

Reuses the same pieces the explicit subcommands already use rather than
reimplementing anything:

- which games are usable: doctor.py's per-game ``check_ds_install`` /
  ``check_hzd_package`` / ``check_fw_package`` functions -- the single source
  of truth for "found" vs "not configured" vs "configured but broken".
- dispatch: :func:`deciwaves.cli.run.run_game`, the identical path
  ``deciwaves <game> run`` takes -- chdir into the chosen workspace, then
  ``run_game(game, cfg, [])``. Per-stage progress is whatever that call
  already prints; this module only adds the menu/prompt framing around it.

The one hard rule: if stdin isn't a TTY (CI, pipes, scripted/non-interactive
invocation) this must never block on ``input()`` -- print usage and return a
nonzero exit code instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from deciwaves import __version__
from deciwaves.cli import doctor
from deciwaves.cli.run import run_game

# (key, menu label, banner abbreviation, gpu note)
_GAMES = [
    ("ds", "Death Stranding", "Death Stranding", "no GPU"),
    ("hzd", "Horizon Zero Dawn", "HZD", "GPU"),
    ("fw", "Horizon Forbidden West", "HFW", "GPU"),
]

_CHECKS = {
    "ds": lambda cfg: doctor.check_ds_install(cfg.get("ds_install", "")),
    "hzd": lambda cfg: doctor.check_hzd_package(cfg.get("hzd_package", "")),
    "fw": lambda cfg: doctor.check_fw_package(cfg.get("fw_package", "")),
}


def _detect_games(cfg: dict) -> dict:
    """{game key: found}. "found" means configured *and* valid -- reuses
    doctor.py's check functions (which return ok=True for both a valid
    install and an unconfigured one, distinguished only by message text) so
    that "not configured" vs "configured but broken" logic lives in exactly
    one place.
    """
    found = {}
    for game, check in _CHECKS.items():
        ok, msg = check(cfg)
        found[game] = ok and "not configured" not in msg
    return found


def _usage_message() -> str:
    return ("deciwaves: no subcommand given, and stdin isn't interactive -- "
            "run `deciwaves --help` for usage, or one of: setup, doctor, "
            "ds run, hzd run, fw run.")


def _print_banner(found: dict) -> None:
    parts = [f"{abbrev} {'[ok]' if found[key] else '[--]'}" for key, _label, abbrev, _gpu in _GAMES]
    print(f"DeciWaves {__version__} -- found: " + "  ".join(parts))


def _prompt_game(found: dict) -> str:
    print("Which game do you want to extract?")
    for i, (key, label, _abbrev, gpu_note) in enumerate(_GAMES, start=1):
        suffix = "" if found[key] else "  [not configured]"
        print(f"  {i}) {label} ({gpu_note}){suffix}")

    while True:
        raw = input("> ").strip()
        if raw in ("1", "2", "3"):
            return _GAMES[int(raw) - 1][0]
        print("Please enter 1, 2, or 3.")


def _prompt_workspace(default_ws: str) -> str:
    raw = input(f"Workspace [{default_ws}]: ").strip()
    return raw or default_ws


def run_guided(cfg: dict) -> int:
    """Entry point for bare ``deciwaves`` (no subcommand). Returns an exit code."""
    if not sys.stdin.isatty():
        print(_usage_message())
        return 2

    found = _detect_games(cfg)
    _print_banner(found)

    game = _prompt_game(found)
    if not found[game]:
        label = next(label for key, label, _abbrev, _gpu in _GAMES if key == game)
        print(f"{label} isn't set up yet -- run `deciwaves setup` first.")
        return 1

    default_ws = str(Path.cwd())
    workspace = _prompt_workspace(default_ws)

    ws = Path(workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    os.chdir(ws)                      # same contract as main.py's `run` dispatch
    return run_game(game, cfg, [])
