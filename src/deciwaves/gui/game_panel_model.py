"""Qt-free per-game panel model (#73, spec §7): the pure building blocks for the adaptive
per-game panel -- which controls each game shows (hide-not-grey), the FW ``types.json``
gate grading, the scan-warning copy, the render-scope defaults + sample-cap default, and
the standalone DS re-order argv. All strings/constants/logic live here so the thin Qt
:mod:`deciwaves.gui.views.game_panel` widget only adds widgets and wiring, and the contract
is unit-tested on the base ``.[test]`` install (mirrors :mod:`deciwaves.gui.export_model`).

Import-light on purpose: reads config dicts and does plain ``os.path`` checks; it never
imports ``deciwaves.games.*`` at module scope (those pull pydecima / heavy parsers). The FW
types.json grade is a plain :func:`os.path.isfile` on the effective path, matching the
existence semantics of ``games.fw.subtitle_bind.types_json_error`` without importing it.
:func:`check_gamescript` is the one exception and imports lazily *inside* the call:
``games.fw.gamescript`` is pure-stdlib (``re``/``dataclasses``/``pathlib``, no pydecima), and
grading a gamescript by anything other than the real parser would let the two drift apart.
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

# The known tier tokens FW understands. Any token outside this set is an input error.
_FW_VALID_TIERS = {"1", "2", "S", "W", "D"}

# Hint shown near the FW tiers field to warn that scope-narrowing can drop checked rows.
FW_TIERS_HINT = "Checked rows whose tier is outside the entered tiers will be dropped."

def validate_fw_tiers(text: str) -> tuple[bool, list[str]]:
    """Return ``(is_valid, unknown_tokens)`` for a comma-separated tiers string.

    Every token in *text* (whitespace-stripped, empty tokens skipped) must be a member of
    the known tier set ``{1,2,S,W,D}``. An empty *text* (the user cleared the field) is
    considered valid -- ``render_scope()`` falls back to ``FW_TIERS_DEFAULT`` at access time.
    """
    tokens = [t.strip() for t in text.split(",") if t.strip()]
    unknown = [t for t in tokens if t not in _FW_VALID_TIERS]
    return len(unknown) == 0, unknown


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


# The one-line format contract, shown at the FW gamescript picker so a GUI-only user does
# not have to find docs/BYO.md to learn what the file should look like.
GAMESCRIPT_FORMAT_HINT = (
    'Plain text, one "Speaker: text" line per spoken line. ALL-CAPS lines become '
    "quest/section headers; [bracketed] lines are skipped. See docs/BYO.md."
)


def check_gamescript(path: str) -> tuple[str, str]:
    """``("ok"|"empty"|"unreadable", message)`` for a picked BYO gamescript.

    Graded by running the *real* parser (``games.fw.gamescript.parse_file``) rather than a
    lookalike check, so this can never disagree with what ``fw match`` will actually see.

    This exists because the parser is regex-only and never raises: a file in the wrong shape
    (timestamps, ``Speaker - text`` dashes, ``**Speaker:**`` markdown) parses to *zero* lines,
    and ``subtitle_match`` has no empty guard -- it just writes a header-only manifest. Picking
    such a file used to be indistinguishable from supplying no gamescript at all, so the
    "empty" grade is the whole point of the check, not an edge case.
    """
    # Lazy + local: keeps this module's import graph free of deciwaves.games.* (see docstring).
    from deciwaves.games.fw.gamescript import parse_file
    try:
        lines = parse_file(path)
    except (OSError, UnicodeDecodeError) as exc:
        return "unreadable", f"Could not read this file: {exc.__class__.__name__}."
    if not lines:
        return "empty", (
            "No dialogue lines found - this file will behave exactly like no gamescript "
            "at all (no speakers, no story order). " + GAMESCRIPT_FORMAT_HINT
        )
    speakers = len({ln.speaker for ln in lines})
    sections = len({ln.quest for ln in lines if ln.quest})
    return "ok", f"Parsed {len(lines):,} lines, {speakers} speakers, {sections} sections."


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
