"""Where each game writes its pipeline artifacts, and which CSV feeds render.

Qt-free and dependency-free, like :mod:`deciwaves.gui.cli_command` and
:mod:`deciwaves.gui.theme`: three GUI models need this and none of them should own it.

Both facts here were previously duplicated. ``out_dir`` was defined identically in
``export_model``, ``library_model`` and ``progress_model``; the per-game render-input
candidate table was defined twice (``export_model._pipeline_input_source`` and
``progress_model._render_input_source_path``) with the same names in the same fallback
order. That is knowledge-level duplication, not a coincidence of shape: rename one
pipeline artifact and the Library, the Export gate and the progress bar would have
disagreed about which CSV is the render input, silently and in three places.

Deliberately NOT here: the GUI-owned override paths (``imported-order.csv``,
``render-selection.csv``) and the override-aware ``render_input_source``. Those are
export's own namespace and precedence rule, they have one caller each, and hoisting them
would make this module a grab-bag of unrelated path logic.
"""
from __future__ import annotations

import os

# The pipeline's render-input CSV per game, in fallback order. First existing file wins.
# DS: story order from `ds order`. HZD: the bind manifest. FW: the full-reel manifest,
# else what a user with types.json but no BYO gamescript gets from `subtitle-bind`.
_RENDER_INPUT_CANDIDATES = {
    "ds": ("playlist.csv",),
    "hzd": ("asr-manifest.csv",),
    "fw": ("full-reel-manifest.csv", "subtitle-manifest-full.csv"),
}


def out_dir(workspace: str, game: str) -> str:
    """Artifact root for *game*: ``out/`` for DS, ``out/<game>/`` for HZD/FW (spec §9 #6)."""
    return os.path.join(workspace, "out") if game == "ds" else os.path.join(workspace, "out", game)


def pipeline_render_input(workspace: str, game: str) -> str | None:
    """The pipeline's own render-input CSV for *game*, ignoring any manual-order override.

    ``None`` when the stage that writes it has not run yet (pre-``order`` for DS,
    pre-``bind`` for HZD, pre-``subtitle-bind`` for FW) or for an unknown game.
    Callers wanting the override-aware answer want ``export_model.render_input_source``.
    """
    root = out_dir(workspace, game)
    for name in _RENDER_INPUT_CANDIDATES.get(game, ()):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None
