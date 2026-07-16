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
from pathlib import Path
from typing import NamedTuple


class Located(NamedTuple):
    """Where :func:`resolve`'s value came from -- ``deciwaves doctor``'s
    ``check_tool`` needs to report WHICH of the three sources matched (and
    say so in its human-readable report line), which the plain path
    ``resolve()`` returns on its own can't distinguish.
    """
    path: str
    source: str  # "env" | "tools_dir" | "PATH" | "" (not found)


def locate(env_var: str, exe: str, tools_dir: str = "") -> Located:
    """The shared env var -> (optional) tools_dir -> PATH resolution order
    used by both :func:`resolve` (the spawn-time path lookup every stage
    uses) and `deciwaves doctor`'s ``check_tool`` (which additionally needs
    to know and report *which* of those three sources matched). Previously
    ``check_tool`` reimplemented this whole order itself, independently of
    this module (issue #51 item 1).

    ``tools_dir``, when given, is consulted between the env var and PATH --
    exactly where `deciwaves setup` puts the tools it fetches -- but never
    overrides an explicitly-set env var. Passing ``tools_dir=""`` (the
    default) reproduces ``resolve()``'s original two-source behavior byte
    for byte: every existing call site (``engine/audio_clip.py``,
    ``games/fw/extract.py``, ``games/hzd/atrac9.py``) keeps its env
    var -> PATH -> bare-name behavior unchanged; only doctor's ``check_tool``
    passes a real ``tools_dir``.

    The env var, when SET, is returned unconditionally (even pointing at
    nothing real) -- a broken override must fail loudly at subprocess-spawn
    time (or be caught by doctor first) rather than silently falling through
    to tools_dir/PATH.
    """
    if env_var and os.environ.get(env_var):
        return Located(os.environ[env_var], "env")
    if tools_dir:
        names = {exe} if exe.lower().endswith(".exe") else {exe, exe + ".exe"}
        for name in names:
            candidate = Path(tools_dir) / name
            if candidate.is_file():
                return Located(str(candidate), "tools_dir")
    found = shutil.which(exe)
    if found:
        return Located(found, "PATH")
    return Located(exe, "")


def resolve(env_var: str, exe: str, tools_dir: str = "") -> str:
    """Resolve a decoder executable path: explicit env var override, then
    (optionally) a copy in ``tools_dir``, then a PATH lookup, then the bare
    exe name (fails loudly at subprocess-spawn time if truly absent -- see
    `deciwaves doctor` for a friendlier preflight check).
    """
    return locate(env_var, exe, tools_dir).path
