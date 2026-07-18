"""Qt-free per-game panel model (#73, spec §7): the pure building blocks for the adaptive
per-game panel -- which controls each game shows (hide-not-grey), the FW ``types.json``
gate grading, the scan-warning copy, the render-scope defaults + sample-cap default, and
the standalone DS re-order argv. All strings/constants/logic live here so the thin Qt
:mod:`deciwaves.gui.views.game_panel` widget only adds widgets and wiring, and the contract
is unit-tested on the base ``.[test]`` install (mirrors :mod:`deciwaves.gui.export_model`).

Import-light on purpose: reads config dicts and does plain ``os.path`` checks; it never
imports ``deciwaves.games.*`` (those pull pydecima / heavy parsers). The FW types.json grade
is a plain :func:`os.path.isfile` on the effective path, matching the existence semantics of
``games.fw.subtitle_bind.types_json_error`` without importing it.
"""
from __future__ import annotations

import os

from deciwaves.gui.cli_command import build_cli_command

# Control names -- the per-game visibility set the widget hides/shows on. Kept as bare
# strings so the Qt-free model and its tests share one vocabulary with the widget.
CTRL_GPU = "gpu"                # GPU/CUDA readiness block (HZD, FW)
CTRL_SAMPLE_CAP = "sample_cap"  # ASR sample-cap spinner (HZD)
CTRL_TRANSCRIPT = "transcript"  # BYO narrative transcript picker + re-order (DS)
CTRL_MAIN_STORY = "main_story"  # --main-story render-scope toggle (DS)
CTRL_SPINE_ONLY = "spine_only"  # --spine-only render-scope toggle (HZD)
CTRL_TYPES_JSON = "types_json"  # REQUIRED BYO types.json picker (FW)
CTRL_GAMESCRIPT = "gamescript"  # optional BYO gamescript picker (FW)
CTRL_TIERS = "tiers"            # --tiers render-scope selector (FW)

_CONTROLS = {
    "ds": frozenset({CTRL_TRANSCRIPT, CTRL_MAIN_STORY}),
    "hzd": frozenset({CTRL_GPU, CTRL_SAMPLE_CAP, CTRL_SPINE_ONLY}),
    "fw": frozenset({CTRL_GPU, CTRL_TYPES_JSON, CTRL_GAMESCRIPT, CTRL_TIERS}),
}

# The HZD ASR sample cap the panel's first bind applies (spec §7): a bounded default so the
# first bind reaches a listenable result fast; the coverage bar's "Transcribe all" escalation
# (escalate_bind_argv, --from bind --sample-cap 0) is the uncapped path. Matches the bind
# stage's own default (games.hzd.asr_bind --sample-cap) so the panel and stage agree.
SAMPLE_CAP_DEFAULT = 300

# FW render-scope default (spec §7): render.DEFAULT_TIERS's value, kept here as a string so the
# widget stays Qt-only and this constant is the tested source of truth for the panel default.
FW_TIERS_DEFAULT = "1,2,S"

# Scan-warning copy (spec §7 "Scan warning copy" row) -- this text does not exist elsewhere;
# it is introduced here as the single source. Each names the cost the Scan button incurs.
_SCAN_WARNINGS = {
    "ds": "Scan runs in minutes on CPU.",
    "hzd": "Scan is quick; bind may take hours (GPU).",
    "fw": "Scan is quick; asr may take hours (GPU).",
}


def controls_for(game: str) -> frozenset[str]:
    """The set of control names *game*'s panel shows (spec §7). Everything not in the set is
    HIDDEN (``setVisible(False)``), never greyed. An unknown game shows nothing."""
    return _CONTROLS.get(game, frozenset())


def effective_types_path(workspace: str, cfg: dict) -> str:
    """The FW ``types.json`` path in effect: the configured ``fw_types`` (``deciwaves setup
    --fw-types``) when set, else ``types.json`` in the workspace root (subtitle-bind's own
    default location). An empty configured value (config's "clear" state) falls back to the
    workspace default."""
    return cfg.get("fw_types") or os.path.join(workspace, "types.json")


def types_status(workspace: str, cfg: dict) -> tuple[str, str]:
    """``("ok"|"missing", path)`` for the FW types.json gate, graded by a plain
    :func:`os.path.isfile` on :func:`effective_types_path` -- matching the existence check
    ``subtitle_bind.types_json_error`` performs, without importing the heavy FW stage. This
    grades the FW picker satisfied(green)/required-missing(red)."""
    path = effective_types_path(workspace, cfg)
    return ("ok" if os.path.isfile(path) else "missing"), path


def scan_warning(game: str) -> str:
    """The per-game Scan-button cost warning (spec §7). Empty for an unknown game."""
    return _SCAN_WARNINGS.get(game, "")


def render_scope_defaults(game: str) -> dict:
    """The render-scope control defaults for *game* (spec §7):

    - DS ``{"main_story": False}`` -- OFF by default so the GUI's out-of-box export renders
      exactly the checked rows (#72's filtered-manifest contract). ``--main-story`` is an
      opt-in scope-narrowing on top, analogous to the FW ``--tiers`` narrowing.
    - HZD ``{"spine_only": False}`` -- OFF by default (keep every checked row).
    - FW ``{"tiers": "1,2,S"}`` -- the shipped default tier set.
    """
    return {
        "ds": {"main_story": False},
        "hzd": {"spine_only": False},
        "fw": {"tiers": FW_TIERS_DEFAULT},
    }.get(game, {})


def transcript_order_argv(base: list[str], workspace: str, transcript_path: str) -> list[str]:
    """The STANDALONE ``deciwaves --workspace <abs> ds order --transcript <abs>`` argv for the
    DS panel's "Re-order with transcript" affordance (spec §7: reachable ONLY here, never
    through ``ds run``).

    Threads the packaged ``ds/cutscene_tracks.csv`` via ``--cutscene-tracks`` exactly as
    ``cli.run._ds_order_argv`` does for the chained order stage: a bare standalone ``ds order``
    defaults ``--cutscene-tracks`` to ``out/cutscene_tracks.csv``, which only the optional
    ``ds cutscenes`` stage ever writes -- so without this the re-order would fail on a
    workspace that was only scanned via ``run``. If this build doesn't bundle the file, the
    flag is omitted and the stage surfaces its own not-found error in the log. The transcript
    path is absolutized (the GUI is always-absolute, spec §4)."""
    tokens = ["order", "--transcript", os.path.abspath(transcript_path)]
    try:
        from deciwaves import data
        tokens += ["--cutscene-tracks", str(data.packaged("ds/cutscene_tracks.csv"))]
    except FileNotFoundError:
        pass
    return build_cli_command(base, workspace, "ds", *tokens)
