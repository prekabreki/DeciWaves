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

The three game-install checks (``check_ds_install`` / ``check_hzd_package`` /
``check_fw_package``) return a :class:`CheckResult` instead of a bare tuple:
alongside the human-readable ``message``, it carries a structured
:class:`Availability` (``OK`` / ``NOT_CONFIGURED`` / ``BROKEN``) so a caller
that needs to distinguish "not configured" from "configured and valid" --
guided.py's game-availability menu, specifically -- can branch on that status
directly instead of substring-matching the message text for "not configured"
(issue #32: that substring match broke the moment a message legitimately
mentioned those words for an unrelated reason). ``CheckResult`` still unpacks
as a plain ``(ok, message)`` 2-tuple -- ``run_doctor``'s own loop below, and
every other existing check function, keep the bare-tuple shape unchanged.
"""
from __future__ import annotations

import argparse
import enum
import os
import shutil
from pathlib import Path
from typing import NamedTuple

from deciwaves.cli import config
from deciwaves.engine import tool_paths
from deciwaves.games.hzd import profile as hzd_profile


class Availability(enum.Enum):
    """Tri-state install/config status for a game-availability check."""
    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    BROKEN = "broken"


class CheckResult(NamedTuple):
    """A game-availability check's outcome. Unpacks as ``(ok, message)`` --
    see ``__iter__`` -- so it drops into `run_doctor`'s existing
    ``for passed, msg in checks`` loop, and every existing
    ``ok, msg = check_x(...)`` call site/test, unchanged. ``status`` is the
    structured signal callers that need more than pass/fail (guided.py)
    should read instead of the message text.
    """
    status: Availability
    message: str

    @property
    def ok(self) -> bool:
        return self.status is not Availability.BROKEN

    def __iter__(self):
        yield self.ok
        yield self.message


# --- tool resolution ---------------------------------------------------
# Mirrors the resolution order engine.tool_paths.resolve() uses at
# subprocess-spawn time (engine/audio_clip.py, games/fw/extract.py,
# games/hzd/atrac9.py), plus main.py's ffmpeg-via-PATH usage in
# engine/audio_clip.py's silence detection: explicit env var override,
# then a copy in the configured tools_dir, then bare name on PATH.


def check_tool(display: str, exe: str, env_var: str | None, tools_dir: str) -> tuple[bool, str]:
    """Resolve *exe* the same way the pipeline will: env var -> tools_dir -> PATH.

    The actual env var -> tools_dir -> PATH order is delegated to
    ``engine.tool_paths.locate()`` -- the same function ``resolve()`` (what
    stages call at decode-subprocess-spawn time) is built on -- instead of
    reimplementing it here (issue #51 item 1: this used to be a second,
    independent copy of that order). This function's own job is the
    doctor-specific part on top: validating that a SET env var actually
    resolves to something usable, and turning the result into a
    human-readable report line.

    An env var that's set but resolves to nothing usable is reported as a
    failure, not silently accepted: ``engine/tool_paths.py``'s own ``resolve()``
    uses the env var unconditionally when set (broken or not), so this is exactly
    the failure mode doctor exists to catch before a decode subprocess fails at
    spawn time. "Usable" matches what ``subprocess.run`` accepts, though (finding
    5): a value that is either an existing file OR a bare name resolvable on PATH
    (``shutil.which``) works at spawn time, so doctor must not fail it just
    because it isn't an absolute file path -- that rejected a working config.
    """
    found = tool_paths.locate(env_var, exe, tools_dir)
    if found.source == "env":
        p = found.path
        if not Path(p).is_file() and not shutil.which(p):
            return False, (f"[--] {display}: env {env_var} is set to {p}, but that "
                            f"file doesn't exist (and it isn't on PATH). Fix: unset "
                            f"{env_var} or point it at the real executable.")
        return True, f"[ok] {display}: {p} (env {env_var})"
    if found.source == "tools_dir":
        return True, f"[ok] {display}: {found.path} (tools_dir)"
    if found.source == "PATH":
        return True, f"[ok] {display}: {found.path} (PATH)"
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

def check_ds_install(ds_install: str) -> CheckResult:
    if not ds_install:
        return CheckResult(Availability.NOT_CONFIGURED,
                            "[--] DS install: not configured (fine if you don't own it)")
    if Path(ds_install, "data").is_dir():
        return CheckResult(Availability.OK, f"[ok] DS install: {ds_install}")
    return CheckResult(Availability.BROKEN,
                        f"[--] DS install: {ds_install!r} has no data/ dir. "
                        f"Fix: run `deciwaves setup --ds-install <game root>`.")


def check_hzd_package(hzd_package: str) -> CheckResult:
    """The "does this look like a real HZDR package dir" predicate itself is
    ``games.hzd.profile.is_valid_hzd_package_dir`` -- shared with ``cli.setup``'s
    ``_hzd_package_warning`` and ``games.hzd.profile.hzd_package_error``
    (issue #51 item 2); this function's own report wording stays as-is."""
    if not hzd_package:
        return CheckResult(Availability.NOT_CONFIGURED,
                            "[--] HZD package: not configured (fine if you don't own it)")
    if hzd_profile.is_valid_hzd_package_dir(hzd_package):
        return CheckResult(Availability.OK, f"[ok] HZD package: {hzd_package}")
    return CheckResult(Availability.BROKEN,
                        f"[--] HZD package: {hzd_package!r} has no PackFileLocators.bin. "
                        f"This must be the ...\\LocalCacheDX12\\package directory (the one "
                        f"containing PackFileLocators.bin), not the game install root. "
                        f"Fix: run `deciwaves setup --hzd-package <...\\LocalCacheDX12\\package>`.")


def check_fw_package(fw_package: str) -> CheckResult:
    if not fw_package:
        return CheckResult(Availability.NOT_CONFIGURED,
                            "[--] FW package: not configured (fine if you don't own it)")
    if Path(fw_package, "streaming_graph.core").is_file():
        return CheckResult(Availability.OK, f"[ok] FW package: {fw_package}")
    return CheckResult(Availability.BROKEN,
                        f"[--] FW package: {fw_package!r} has no streaming_graph.core. "
                        f"Fix: run `deciwaves setup --fw-package <...\\LocalCacheWinGame\\package>`.")


def check_fw_gamescript(fw_gamescript: str) -> tuple[bool, str]:
    """Unlike check_fw_package, "not configured" here is a normal, fully-supported
    state -- the FW gamescript is BYO and optional even when FW itself is owned (it
    only gates match/full-reel/render's speaker + story-order matching; without it
    `fw run` still produces subtitle-labeled reels). But once it HAS been configured
    (via `deciwaves setup --fw-gamescript`) and later goes missing, that's the same
    "configured but broken" failure as the other game checks -- it was explicitly
    pointed at a path, just earlier."""
    if not fw_gamescript:
        return True, ("[--] FW gamescript: not configured (optional, BYO -- only needed for "
                       "speaker + story-order matching; see docs/BYO.md)")
    if Path(fw_gamescript).is_file():
        return True, f"[ok] FW gamescript: {fw_gamescript}"
    return False, (f"[--] FW gamescript: {fw_gamescript!r} not found. "
                    f"Fix: run `deciwaves setup --fw-gamescript <path>` with the correct path, "
                    f"or pass --gamescript explicitly to `deciwaves fw run`.")


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
        *[check_tool(t.display, t.exe, t.env_var, tools_dir) for t in config.TOOLS],
        check_oodle(cfg.get("oodle_dll", ""), cfg.get("ds_install", "")),
        check_ds_install(cfg.get("ds_install", "")),
        check_hzd_package(cfg.get("hzd_package", "")),
        check_fw_package(cfg.get("fw_package", "")),
        check_fw_gamescript(cfg.get("fw_gamescript", "")),
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
