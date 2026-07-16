"""``deciwaves`` with no subcommand: a thin guided interactive flow (Task 17).

Reuses the same pieces the explicit subcommands already use rather than
reimplementing anything:

- which games are usable: doctor.py's per-game ``check_ds_install`` /
  ``check_hzd_package`` / ``check_fw_package`` functions -- the single source
  of truth for "found" vs "not configured" vs "configured but broken", read
  off each check's structured ``doctor.Availability`` status, not its message
  text (issue #32).
- dispatch: :func:`deciwaves.cli.run.run_game`, the identical path
  ``deciwaves <game> run`` takes -- chdir into the chosen workspace, then
  ``run_game(game, cfg, [])``. Per-stage progress is whatever that call
  already prints; this module only adds the menu/prompt framing around it.

The one hard rule: if stdin isn't a TTY (CI, pipes, scripted/non-interactive
invocation) this must never block on ``input()`` -- print usage and return a
nonzero exit code instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

from deciwaves import __version__
from deciwaves.cli import config, doctor
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
    doctor.py's check functions, reading each one's structured
    ``doctor.Availability`` status (issue #32: this used to substring-match
    the human-readable message for "not configured", which broke the moment
    a message legitimately contained those words for an unrelated reason) so
    that "not configured" vs "configured but broken" logic lives in exactly
    one place.
    """
    found = {}
    for game, check in _CHECKS.items():
        result = check(cfg)
        found[game] = result.status is doctor.Availability.OK
    return found


def _usage_message() -> str:
    return ("deciwaves: no subcommand given, and stdin isn't interactive -- "
            "run `deciwaves --help` for usage, or one of: setup, doctor, "
            "ds run, hzd run, fw run.")


def _print_banner(found: dict) -> None:
    parts = [f"{abbrev} {'[ok]' if found[key] else '[--]'}" for key, _label, abbrev, _gpu in _GAMES]
    print(f"DeciWaves {__version__} -- found: " + "  ".join(parts))


def _prompt_game(found: dict) -> str | None:
    print("Which game do you want to extract?")
    for i, (key, label, _abbrev, gpu_note) in enumerate(_GAMES, start=1):
        suffix = "" if found[key] else "  [not configured]"
        print(f"  {i}) {label} ({gpu_note}){suffix}")

    valid = tuple(str(i) for i in range(1, len(_GAMES) + 1))
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw in valid:
            return _GAMES[int(raw) - 1][0]
        print(f"Please enter {', '.join(valid[:-1])}, or {valid[-1]}.")


def _prompt_workspace(default_ws: str) -> str | None:
    try:
        raw = input(f"Workspace [{default_ws}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return raw or default_ws


def _prompt_gamescript(default: str) -> str | None:
    """Ask for the (optional, BYO) FW gamescript path. Enter alone keeps
    ``default`` -- the already-configured `fw_gamescript`, if any, or "" (skip)
    when nothing is configured -- same default-on-blank shape as
    `_prompt_workspace`. Returning "" (not None) means "skip gracefully";
    only an EOFError (non-interactive edge case) returns None."""
    print("Optional: your own Forbidden West gamescript transcript, for speaker + "
          "story-order matching (BYO -- this repo can't ship game text; see docs/BYO.md). "
          "Leave blank to skip for now -- you can still supply it later with "
          "`deciwaves fw run --gamescript <path>` or `deciwaves setup --fw-gamescript <path>`.")
    suffix = f" [{default}]" if default else " [skip]"
    try:
        raw = input(f"Gamescript path{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return raw or default


def run_guided(cfg: dict, workspace: str | None = None) -> int:
    """Entry point for bare ``deciwaves`` (no subcommand). Returns an exit code.

    ``workspace``, when given, is used as the workspace prompt's default (issue
    #32: bare `deciwaves --workspace X` used to silently ignore --workspace
    here, always defaulting the prompt to ``Path.cwd()`` instead) -- ``None``
    (the default, e.g. when calling this directly in a test) falls back to the
    process cwd, same as before this parameter existed.
    """
    if not sys.stdin.isatty():
        print(_usage_message())
        return 2

    found = _detect_games(cfg)
    _print_banner(found)

    game = _prompt_game(found)
    if game is None:
        print(_usage_message())
        return 2
    if not found[game]:
        label = next(label for key, label, _abbrev, _gpu in _GAMES if key == game)
        print(f"{label} isn't set up yet -- run `deciwaves setup` first.")
        return 1

    default_ws = workspace or str(Path.cwd())
    workspace = _prompt_workspace(default_ws)
    if workspace is None:
        print(_usage_message())
        return 2

    extra_argv = []
    if game == "fw":
        gamescript = _prompt_gamescript(cfg.get("fw_gamescript", ""))
        if gamescript is None:
            print(_usage_message())
            return 2
        if gamescript:
            extra_argv = ["--gamescript", gamescript]

    # Same as main.py's stage dispatch: absolutize a relative --gamescript
    # BEFORE the chdir below, so it keeps pointing at the file the user meant
    # (relative to where they ran `deciwaves` from) instead of being looked
    # up inside the workspace (issue #32).
    extra_argv = config.absolutize_existing_paths(extra_argv)
    config.enter_workspace(workspace)  # same contract as main.py's `run` dispatch
    return run_game(game, cfg, extra_argv)
