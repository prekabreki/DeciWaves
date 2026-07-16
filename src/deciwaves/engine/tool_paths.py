"""Spawn-time resolution for decoder executables (`vgmstream-cli`, `VGAudioCli`).

`engine/audio_clip.py`, `games/fw/extract.py`, and `games/hzd/atrac9.py` used to
freeze `DECIWAVES_VGMSTREAM` / `DECIWAVES_VGAUDIO` into module-level constants
(and, for `clip_wav`, a `vgmstream=VGMSTREAM` default arg) at import time. That
meant the CLI had to call `_apply_config_env()` before importing any stage
module, or the frozen constant would never see the configured tool path --
a temporal coupling with no compiler or test to enforce it.

`resolve()` reads the env var when a subprocess is actually about to be
spawned instead, so it no longer matters when config gets applied relative to
import: only that it happens before the decode subprocess runs.
"""
from __future__ import annotations

import os
import shutil


def resolve(env_var: str, exe: str) -> str:
    """Resolve a decoder executable path: explicit env var override, then a
    PATH lookup, then the bare exe name (fails loudly at subprocess-spawn
    time if truly absent -- see `deciwaves doctor` for a friendlier
    preflight check).
    """
    return os.environ.get(env_var) or shutil.which(exe) or exe
