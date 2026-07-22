"""DeciWaves GUI package (issue #67).

This module surface is import-safe WITHOUT PySide6 so ``cli/main`` can decide whether
to launch the GUI, and the guided fallback still works on a base install. Anything that
imports PySide6 lives in submodules (``app``, ``shell``, ``jobs``, ...) imported lazily
inside :func:`launch`."""
from __future__ import annotations

import importlib.util

INSTALL_HINT = 'pip install "deciwaves[gui]"'
ASR_INSTALL_HINT = "pip install deciwaves[asr]"


def is_available() -> bool:
    """True iff the ``[gui]`` extra (PySide6) is importable. Does NOT import it."""
    return importlib.util.find_spec("PySide6") is not None


def launch(argv=None) -> int:
    """Launch the desktop GUI. Lazy-imports the Qt app so importing this package never
    requires PySide6. Returns a process exit code."""
    if not is_available():
        print(f"The DeciWaves GUI needs the [gui] extra. Install it with:\n    {INSTALL_HINT}")
        return 1
    # Apply persisted tool paths (DECIWAVES_VGMSTREAM/VGAUDIO) here too: the `deciwaves-gui`
    # gui_scripts shortcut lands on this function directly, bypassing cli.main()'s own
    # _apply_config_env(), so without this inline preview (#71) couldn't find the decoders.
    from deciwaves.cli import config
    config.apply_tool_env()
    from deciwaves.gui.app import run_app
    return run_app(argv)
