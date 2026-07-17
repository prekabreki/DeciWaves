"""Persisted config: where setup put the tools and where the games live."""
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple, Optional

from deciwaves.engine.atomic_io import atomic_write

KEYS = ("tools_dir", "ds_install", "hzd_package", "fw_package", "oodle_dll", "fw_gamescript")

# --- decode tool metadata -------------------------------------------------
# Single source of truth for the three decode tools `deciwaves setup` fetches.
# Previously triplicated -- main.py's _apply_config_env (exe name + env var,
# for PATH/env wiring), doctor.py's check_tool(...) call sites (display name +
# exe name + env var), and setup.py's own _TOOLS (label + url + exe) each
# spelled the same facts out independently, with the exe name spelled two
# different ways between them ("vgmstream-cli.exe" in main.py/setup.py vs.
# bare "vgmstream-cli" in doctor.py) (issue #32). `key`/`display` keep their
# two previously-distinct spellings (setup's short summary-row label vs.
# doctor's own display name) so consolidating this doesn't change either
# module's printed text -- only the facts themselves (exe filename, env var,
# URL) are now defined exactly once.

# Pinned 2026-07-14 via:
#   gh release view --repo vgmstream/vgmstream --json assets -q '.assets[].name' | grep -i win
#   gh release view --repo Thealexbarney/VGAudio --json assets -q '.assets[].name'
#   gh release view autobuild-2026-07-14-13-19 --repo BtbN/FFmpeg-Builds --json assets -q '.assets[].name' | grep win64-gpl.zip
#
# BtbN/FFmpeg-Builds has no versioned tags -- "latest" is a rolling alias that
# always points at whatever the newest autobuild-YYYY-MM-DD-HH-MM release is,
# so it is NOT a pin (issue #39). Pin to that dated autobuild tag's master
# build instead, same as vgmstream/VGAudio pin to a fixed release/tag.
VGMSTREAM_URL = "https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip"
VGAUDIO_URL = "https://github.com/Thealexbarney/VGAudio/releases/download/v2.2.1/VGAudioCli.zip"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-14-13-19/ffmpeg-N-125608-g150f7d15df-win64-gpl.zip"


class ToolSpec(NamedTuple):
    key: str                       # setup's short summary-row label
    display: str                   # doctor's human display name
    exe: str                       # canonical exe filename (with .exe) in tools_dir
    env_var: Optional[str]         # explicit override env var, or None (ffmpeg has none)
    url: str                       # pinned download URL (issue #39)


TOOLS = (
    ToolSpec("vgmstream", "vgmstream-cli", "vgmstream-cli.exe", "DECIWAVES_VGMSTREAM", VGMSTREAM_URL),
    ToolSpec("VGAudio",   "VGAudioCli",    "VGAudioCli.exe",    "DECIWAVES_VGAUDIO",   VGAUDIO_URL),
    ToolSpec("ffmpeg",    "ffmpeg",        "ffmpeg.exe",        None,                  FFMPEG_URL),
)

def path() -> Path:
    root = os.environ.get("DECIWAVES_CONFIG_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "DeciWaves")
    return Path(root) / "config.json"

def _warn_corrupted(cfg_path: Path, reason) -> None:
    print(
        f"warning: config file {cfg_path} is corrupted ({reason}); "
        "ignoring it and starting fresh -- run `deciwaves setup` to repair."
    )

def load() -> dict:
    cfg_path = path()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        _warn_corrupted(cfg_path, exc)
        return {}
    if not isinstance(cfg, dict):
        _warn_corrupted(cfg_path, f"expected a JSON object, got {type(cfg).__name__}")
        return {}
    return cfg

# Flags whose value is a STAGE NAME, never a path (run.py's --until/--from,
# issue #62): a cwd file/dir that happens to share a stage's name (`extract`,
# `render`, `catalog`, ...) must not get absolutized into an argparse-choices
# rejection -- or worse, an exists-in-both-trees exit-2 refusal.
_NON_PATH_VALUE_FLAGS = frozenset({"--until", "--from"})


def absolutize_existing_paths(argv: list, workspace=None) -> list:
    """Resolve any argv token that refers to an EXISTING file/dir relative to
    the CURRENT (pre-chdir) cwd to its absolute form -- but only when a
    *different* --workspace is actually about to move "relative" out from
    under it, and only when doing so is unambiguous.

    Call this before `enter_workspace()` changes what "relative" means. A
    relative path the user typed to mean "relative to where I ran deciwaves"
    (a BYO gamescript, an install dir, ...) must keep pointing at the same
    place once the process chdirs into --workspace -- otherwise it's
    silently (mis)resolved inside the workspace instead (issue #32).

    *workspace* is the caller's (not yet chdir'd-into) `--workspace` target.
    If it's ``None`` (no --workspace given) or resolves to the same directory
    as cwd, nothing is rewritten at all -- "relative" means the same thing on
    both sides of the (no-op) chdir, so there is nothing to pin. This is
    itself a behavior fix (issue #44): a plain no-workspace run used to
    rewrite tokens and print notices for no reason.

    With a workspace that genuinely differs from cwd, each existing-under-cwd
    token is checked against the workspace too, since a token can just as
    easily already exist there (e.g. a stale `out/...` left by a previous
    in-place run under cwd, later reused with `--workspace` pointed at a
    different tree) -- confirmed aggregate-review failure shape: silently
    absolutizing against cwd in that case pins the run to the OLD tree with no
    error, mixing data across workspaces. So:

    - exists under cwd only -> absolutize against cwd (the BYO-input
      convenience this function exists for).
    - exists under neither (a typo, or a stage's own not-yet-written output
      path) -> left untouched; it still fails whatever stage's own "not
      found" check the same way it always did (see run.py's fw --gamescript
      checks, issue #38), just relative to the workspace instead of cwd -- no
      behavior change for that already-loud, already-nonzero failure case.
    - exists under both and they're the SAME file (e.g. workspace is a
      subdir/hardlink arrangement that happens to coincide) -> unambiguous,
      absolutize against cwd same as the cwd-only case.
    - exists under both and they're DIFFERENT files -> refuse: print which
      token and both candidate absolute paths, and exit 2 (matching this
      CLI's usage-error convention -- see main.py's/run.py's own argparse
      error handling) rather than silently picking one and risking the
      stale-tree mixup above.

    Both the bare two-token form (``--gamescript real.md``) and the joined
    ``--flag=value`` form (``--gamescript=real.md``) are handled: the latter used
    to be skipped wholesale because the whole token starts with '-', leaving the
    #32 bug alive for that spelling (finding 2). Every rewrite prints a one-line
    notice so the invocation-dir -> absolute redirect is never silent.
    """
    if workspace is None:
        return list(argv)
    workspace_path = Path(workspace).resolve()
    if workspace_path == Path.cwd():
        return list(argv)

    out = []
    value_is_stage_name = False
    for tok in argv:
        if value_is_stage_name:
            value_is_stage_name = False
        elif tok.startswith("--") and "=" in tok:
            flag, _, value = tok.partition("=")
            if flag not in _NON_PATH_VALUE_FLAGS:
                resolved = _resolve_against_workspace(value, workspace_path)
                if resolved is not None:
                    tok = f"{flag}={resolved}"
        elif tok in _NON_PATH_VALUE_FLAGS:
            value_is_stage_name = True
        elif tok and not tok.startswith("-") and not os.path.isabs(tok) and os.path.exists(tok):
            resolved = _resolve_against_workspace(tok, workspace_path)
            if resolved is not None:
                tok = resolved
        out.append(tok)
    return out


def _resolve_against_workspace(value: str, workspace_path: Path):
    """Return *value* absolutized against the (pre-chdir) cwd, or ``None`` if
    it should be left exactly as typed (empty, already absolute, or doesn't
    exist relative to cwd at all).

    Raises ``SystemExit(2)`` if *value* ALSO exists relative to
    *workspace_path* and the two candidates are different files -- see
    `absolutize_existing_paths`'s docstring for why silently picking one
    isn't safe here.
    """
    if not value or os.path.isabs(value) or not os.path.exists(value):
        return None
    resolved_cwd = str(Path(value).resolve())
    ws_candidate = workspace_path / value
    if not ws_candidate.exists():
        _print_resolution_notice(value, resolved_cwd)
        return resolved_cwd
    resolved_ws = str(ws_candidate.resolve())
    # samefile (not string equality) so a workspace nested/linked such that the
    # two candidates are literally the same file on disk (issue #44's "workspace
    # == subdir" edge case) isn't mistaken for a genuine conflict.
    if os.path.samefile(resolved_cwd, resolved_ws):
        _print_resolution_notice(value, resolved_cwd)
        return resolved_cwd
    _refuse_ambiguous_path(value, resolved_cwd, resolved_ws)


def _refuse_ambiguous_path(token: str, cwd_candidate: str, workspace_candidate: str) -> None:
    print(
        f"deciwaves: {token!r} exists both relative to the invocation directory "
        f"({cwd_candidate}) and relative to --workspace ({workspace_candidate}), "
        "and they are different files -- pass an absolute path to say which one "
        "you mean.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _print_resolution_notice(original: str, resolved: str) -> None:
    print(f"resolved {original} -> {resolved} (invocation dir)")

def enter_workspace(workspace) -> Path:
    """Resolve *workspace* to an absolute path, create it, and chdir into it.

    Stage modules default their own outputs to CWD-relative `out/` paths, so
    this one call is what lets a single `--workspace` flag (or guided mode's
    workspace prompt) redirect an entire run without touching every stage's
    individual path arguments. Previously duplicated verbatim in both
    cli.main's stage-dispatch path and cli.guided's end-of-flow dispatch
    (issue #32) -- now one shared helper.
    """
    ws = Path(workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    os.chdir(ws)
    return ws

def save(cfg: dict) -> None:
    """Persist *cfg* to config.json atomically, via ``engine.atomic_io.atomic_write``
    (a temp file beside config.json, moved into place with ``os.replace`` only once
    fully written) -- so a crash/interrupt mid-write never leaves config.json half
    written; readers see either the previous file or the complete new one."""
    cfg_path = path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({k: cfg.get(k, "") for k in KEYS}, indent=2)

    def _write(tmp_path):
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(data)

    atomic_write(str(cfg_path), _write)
