"""``deciwaves doctor`` -- preflight: are the decode tools, game installs, and
optional GPU extras where the pipeline expects them?

Each check is a small pure function returning ``(ok: bool, message: str)`` so
they're independently testable (monkeypatch ``shutil.which`` / env vars / a
tmp config, no subprocess needed). ``run_doctor`` wires them together and
prints a report.

Exit-code contract: 0 only when every *required* check passes. Missing tools
or a missing Oodle DLL are required -> they fail the exit code. An
unconfigured game (the user simply doesn't own it) reports ``[--] not
configured`` but its ``ok`` is True -- it must never fail the run. The ASR
extra and CUDA checks are purely informational and always report ``ok=True``
regardless of what they find.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from deciwaves.cli import config

# --- tool resolution ---------------------------------------------------
# Mirrors the resolution order the engine modules use at import time
# (engine/audio_clip.py:VGMSTREAM, games/fw/extract.py:VGAUDIO,
# games/hzd/atrac9.py:VGAUDIO, and main.py's ffmpeg-via-PATH usage in
# engine/audio_clip.py's silence detection): explicit env var override,
# then a copy in the configured tools_dir, then bare name on PATH.


def check_tool(display: str, exe: str, env_var: str | None, tools_dir: str) -> tuple[bool, str]:
    """Resolve *exe* the same way the pipeline will: env var -> tools_dir -> PATH."""
    if env_var and os.environ.get(env_var):
        p = os.environ[env_var]
        return True, f"[ok] {display}: {p} (env {env_var})"
    if tools_dir:
        names = {exe} if exe.lower().endswith(".exe") else {exe, exe + ".exe"}
        for name in names:
            candidate = Path(tools_dir) / name
            if candidate.is_file():
                return True, f"[ok] {display}: {candidate} (tools_dir)"
    found = shutil.which(exe)
    if found:
        return True, f"[ok] {display}: {found} (PATH)"
    return False, (f"[--] {display}: not found. "
                    f"Fix: run `deciwaves setup` to fetch it (or put it on PATH).")


# --- Oodle DLL -----------------------------------------------------------

def check_oodle(oodle_dll: str, ds_install: str = "") -> tuple[bool, str]:
    if not ds_install:
        return True, "[--] Oodle DLL: not needed (DS not configured)"
    if oodle_dll and Path(oodle_dll).is_file():
        return True, f"[ok] Oodle DLL: {oodle_dll}"
    return False, ("[--] Oodle DLL: not found. "
                    "Fix: run `deciwaves setup --ds-install <game root>` "
                    "(oo2core_7_win64.dll ships next to the DS:DC exe).")


# --- game installs: unconfigured never fails the exit code ----------------

def check_ds_install(ds_install: str) -> tuple[bool, str]:
    if not ds_install:
        return True, "[--] DS install: not configured (fine if you don't own it)"
    if Path(ds_install, "data").is_dir():
        return True, f"[ok] DS install: {ds_install}"
    return False, (f"[--] DS install: {ds_install!r} has no data/ dir. "
                    f"Fix: run `deciwaves setup --ds-install <game root>`.")


def check_hzd_package(hzd_package: str) -> tuple[bool, str]:
    if not hzd_package:
        return True, "[--] HZD package: not configured (fine if you don't own it)"
    if Path(hzd_package).is_dir():
        return True, f"[ok] HZD package: {hzd_package}"
    return False, (f"[--] HZD package: {hzd_package!r} not found. "
                    f"Fix: run `deciwaves setup --hzd-package <...\\LocalCacheDX12\\package>`.")


def check_fw_package(fw_package: str) -> tuple[bool, str]:
    if not fw_package:
        return True, "[--] FW package: not configured (fine if you don't own it)"
    if Path(fw_package, "streaming_graph.core").is_file():
        return True, f"[ok] FW package: {fw_package}"
    return False, (f"[--] FW package: {fw_package!r} has no streaming_graph.core. "
                    f"Fix: run `deciwaves setup --fw-package <...\\LocalCacheWinGame\\package>`.")


# --- optional GPU extras: informational, never fail the exit code --------

def check_asr_extra() -> tuple[bool, str]:
    try:
        import whisperx  # noqa: F401
        return True, "[ok] ASR extra (whisperx): installed"
    except ImportError:
        return True, ("[--] ASR extra (whisperx): not installed (only needed for GPU "
                       "stages: ds trim, hzd bind, fw asr). Fix: pip install deciwaves[asr]")


def check_cuda() -> tuple[bool, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return True, f"[ok] CUDA: available ({torch.cuda.get_device_name(0)})"
        return True, "[--] CUDA: torch installed but no GPU visible (informational)"
    except ImportError:
        return True, "[--] CUDA: torch not installed (informational; see ASR extra)"
    except Exception as exc:  # torch can fail to import for env reasons (locked DLLs,
        # broken install); doctor's contract is to report, never traceback.
        reason = str(exc).splitlines()[0][:80]
        return True, f"[--] CUDA: torch import failed ({reason}) (informational)"


def check_config_file() -> tuple[bool, str]:
    return True, f"[ok] config file: {config.path()}"


def run_doctor(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deciwaves doctor",
                                  description="Preflight: tools, installs, and optional extras.")
    ap.parse_args(argv or [])

    cfg = config.load()
    tools_dir = cfg.get("tools_dir", "")

    checks = [
        check_tool("vgmstream-cli", "vgmstream-cli", "DECIWAVES_VGMSTREAM", tools_dir),
        check_tool("VGAudioCli", "VGAudioCli", "DECIWAVES_VGAUDIO", tools_dir),
        check_tool("ffmpeg", "ffmpeg", None, tools_dir),
        check_oodle(cfg.get("oodle_dll", ""), cfg.get("ds_install", "")),
        check_ds_install(cfg.get("ds_install", "")),
        check_hzd_package(cfg.get("hzd_package", "")),
        check_fw_package(cfg.get("fw_package", "")),
        check_asr_extra(),
        check_cuda(),
        check_config_file(),
    ]

    ok = True
    for passed, msg in checks:
        print(msg)
        if not passed:
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_doctor())
