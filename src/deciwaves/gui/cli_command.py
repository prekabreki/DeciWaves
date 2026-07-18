"""Qt-free construction of a ``deciwaves`` subprocess argv (issue #67).

Kept out of ``jobs.py`` so it imports without PySide6 and gets unconditional test
coverage. Enforces the two hard CLI rules the GUI must honor (spec §4, §9): the global
``--workspace`` flag comes BEFORE the game token, and the workspace is an absolute path."""
from __future__ import annotations

import os
import sys


def default_base() -> list[str]:
    """Invoke the CLI through the SAME interpreter running the GUI -- no PATH lookup, so
    a stale global ``deciwaves`` on PATH can't shadow the install the GUI is part of."""
    return [sys.executable, "-m", "deciwaves.cli.main"]


def build_cli_command(base: list[str], workspace: str, game: str, *tokens: str) -> list[str]:
    """``base + --workspace <abs> + game + tokens``.

    ``--workspace`` is placed before the game token deliberately: after it, the CLI
    swallows it as the stage's own argument instead of the global workspace (main.py's
    own help calls this out). ``workspace`` is absolutized because the GUI always passes
    absolute paths, sidestepping the CLI's relative-path heuristics entirely."""
    return [*base, "--workspace", os.path.abspath(workspace), game, *tokens]
