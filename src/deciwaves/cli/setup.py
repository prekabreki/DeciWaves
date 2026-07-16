"""`deciwaves setup` -- fetch the decode tools, locate Oodle, write config.json.

Fetches vgmstream-cli, VGAudioCli, and ffmpeg into a tools dir (default
%LOCALAPPDATA%\\DeciWaves\\tools), locates oo2core_7_win64.dll under a DS
install, and persists everything via `deciwaves.cli.config.save`. Downloads
are plain zips pulled with urllib + unpacked with zipfile -- no extra
dependency, no auth, and the flatten step means callers never need to know
whether the upstream zip nests its exe one folder deep.

URLs are pinned to specific releases (not "latest" redirects) so a run next
year fetches the same bits this one did; see the comment above the URL
constants in `deciwaves.cli.config` (config.TOOLS' single source of truth for
all three tools' metadata, issue #32) for how each pinned asset name was
verified against the upstream releases -- including BtbN/FFmpeg-Builds, whose
own "latest" tag is a rolling alias and therefore not itself a valid pin
(issue #39).
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from deciwaves.cli import config
# VGMSTREAM_URL/VGAUDIO_URL/FFMPEG_URL and the pin provenance comment above them
# now live in config.TOOLS (issue #32: one TOOLS table, not one copy per
# module) -- re-exported here under their old names since tests (and anyone
# scripting against this module) reference `setup.VGMSTREAM_URL` etc. directly.
from deciwaves.cli.config import FFMPEG_URL, VGAUDIO_URL, VGMSTREAM_URL  # noqa: F401

# (label, url, exe expected to land directly in the tools dir once unpacked).
_TOOLS = tuple((t.key, t.url, t.exe) for t in config.TOOLS)

OODLE_DLL_NAME = "oo2core_7_win64.dll"

DOWNLOAD_TIMEOUT_SECONDS = 30


def _default_tools_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA", str(Path.home()))
    return Path(root) / "DeciWaves" / "tools"


def _resolve_or_empty(path_str: str) -> str:
    """Resolve *path_str* to an absolute string, or keep "" as "" (an unset
    field). Every path persisted to config.json is saved absolute: once
    written, "relative to what" has no fixed meaning -- a later `deciwaves`
    invocation can run from any directory, or chdir into an unrelated
    --workspace, before this value is ever read again (issue #32). A relative
    flag is resolved against the cwd *at setup time*, the one point where
    "relative" still has an unambiguous meaning.
    """
    return str(Path(path_str).resolve()) if path_str else ""


def _short_reason(exc: Exception) -> str:
    """Collapse an exception to a short, single-line, ASCII-safe reason
    suitable for a summary table cell -- never a raw traceback."""
    msg = str(exc).strip() or type(exc).__name__
    msg = msg.splitlines()[0]
    msg = msg.encode("ascii", "replace").decode("ascii")
    if len(msg) > 60:
        msg = msg[:57] + "..."
    return msg


def _download_and_unpack(url: str, dest_dir: Path, timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
                          manifest_path: Path | None = None) -> None:
    """Fetch `url` (a zip) and flatten every file it contains directly into
    dest_dir, discarding whatever subfolder structure the upstream zip used.
    vgmstream/VGAudio ship their exe (plus sibling decoder DLLs) at top level;
    the ffmpeg-builds zip nests everything one `ffmpeg-*/bin/` folder deep --
    flattening means the caller never has to special-case either shape.

    Raises whatever urllib/zipfile raises on failure (DNS error, HTTP error,
    timeout, bad zip) -- the caller is responsible for catching this per-tool
    so one bad download doesn't take down the whole run.

    If *manifest_path* is given, it's written -- one extracted filename per
    line, relative to dest_dir -- only AFTER every file has been successfully
    written to disk. This is the "fully and successfully unpacked" record
    `_fetch_tools`' skip-if-present check relies on: an interrupted run that
    raises partway through (a bad zip, a truncated download) leaves whatever
    files it already wrote on disk but never gets here, so no manifest is
    written for that partial state -- the next run correctly treats it as
    not-yet-installed and retries, instead of a present-but-incomplete exe
    silently passing as "already installed" (issue #32 follow-up)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read()
    extracted = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name:
                continue
            with zf.open(info) as src, open(dest_dir / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(name)
    if manifest_path is not None:
        manifest_path.write_text("\n".join(extracted) + "\n", encoding="utf-8")


HZD_LOCATORS_NAME = "PackFileLocators.bin"


def _hzd_package_warning(hzd_package: str) -> str | None:
    """Return a WARNING message if *hzd_package* is set but doesn't look like
    the HZDR ...\\LocalCacheDX12\\package dir (the one containing
    PackFileLocators.bin), else None. Non-blocking -- like the oo2core_7_win64.dll
    check for ds_install, this never fails setup's exit code, it only makes the
    eventual catalog-time failure legible up front (issue #34: setup used to
    accept any existing dir for --hzd-package with zero validation).

    If the user pointed --hzd-package at the game install root, detect that
    ...\\LocalCacheDX12\\package exists underneath and name the exact corrected
    path in the hint, rather than just describing the pattern.
    """
    if not hzd_package:
        return None
    if os.path.isfile(os.path.join(hzd_package, HZD_LOCATORS_NAME)):
        return None
    suggestion = Path(hzd_package) / "LocalCacheDX12" / "package"
    if (suggestion / HZD_LOCATORS_NAME).is_file():
        return (f"WARNING: {hzd_package!r} has no {HZD_LOCATORS_NAME} directly inside -- "
                f"looks like the HZD install root, not the package dir. Did you mean "
                f"--hzd-package {suggestion}?")
    return (f"WARNING: {HZD_LOCATORS_NAME} not found under {hzd_package!r}. "
            f"--hzd-package must point at the ...\\LocalCacheDX12\\package directory "
            f"(the one containing {HZD_LOCATORS_NAME}).")


def _find_oodle(ds_install: str) -> str:
    """Return the path to oo2core_7_win64.dll under ds_install, or "" if
    ds_install wasn't given or doesn't contain it."""
    if not ds_install:
        return ""
    candidate = Path(ds_install) / OODLE_DLL_NAME
    return str(candidate) if candidate.is_file() else ""


def _manifest_path_for(exe: str, tools_dir: Path) -> Path:
    return tools_dir / f"{exe}.files.txt"


def _tool_fully_installed(exe_path: Path, manifest_path: Path, tools_dir: Path) -> bool:
    """True iff *exe_path* exists AND its sidecar manifest -- written by
    `_download_and_unpack` only after every file in its zip was successfully
    extracted -- exists and every file it lists is still present in
    tools_dir.

    A missing manifest (a legacy pre-issue-#32 tools_dir that predates this
    check, or one interrupted mid-unpack before it got written) means "never
    verified as complete", not "installed": the skip-if-present check below
    must fall through to a real re-fetch in that case -- exactly once, since
    that re-fetch writes the manifest, so later runs genuinely skip.
    Previously a present exe ALONE was enough to skip (issue #32's original
    fix) -- which silently treated a partial/interrupted unpack (exe landed,
    a sibling decoder DLL didn't) as fully installed, and only --force could
    recover it. This is the follow-up fix."""
    if not exe_path.is_file() or not manifest_path.is_file():
        return False
    try:
        names = [n for n in manifest_path.read_text(encoding="utf-8").splitlines() if n]
    except OSError:
        return False
    return bool(names) and all((tools_dir / n).is_file() for n in names)


def _fetch_tools(tools_dir: Path, skip_downloads: bool, force: bool = False):
    """Returns ([(label, status, path), ...], any_failed) for the summary
    table and exit-code decision. Each tool's download/unpack is isolated:
    an exception (or a post-unpack missing exe) marks that tool FAILED and
    the loop moves on to the next tool rather than aborting the whole run.

    --skip-downloads never downloads and never counts as a failure -- it
    only reports what's already present ("found"/"MISSING"). Otherwise, a
    tool that's already fully installed (exe present, and its manifest
    confirms every extracted file is still there -- see
    `_tool_fully_installed`) is left alone instead of re-fetched -- most runs
    used to re-download all ~200 MB of tools every time, even when nothing
    was missing (issue #32) -- unless --force says to refetch it anyway."""
    rows = []
    any_failed = False
    for label, url, exe in _TOOLS:
        exe_path = tools_dir / exe
        manifest_path = _manifest_path_for(exe, tools_dir)
        if skip_downloads:
            status = "found" if exe_path.is_file() else "MISSING"
            rows.append((label, status, str(exe_path)))
            continue
        if not force and _tool_fully_installed(exe_path, manifest_path, tools_dir):
            rows.append((label, "found (skipped -- use --force to refetch)", str(exe_path)))
            continue
        try:
            _download_and_unpack(url, tools_dir, manifest_path=manifest_path)
        except Exception as exc:  # fail-soft per tool: record and keep going
            status = f"FAILED: {label} ({_short_reason(exc)})"
            any_failed = True
        else:
            if exe_path.is_file():
                status = "fetched"
            else:
                status = f"FAILED: {label} (exe not found after unpack)"
                any_failed = True
        rows.append((label, status, str(exe_path)))
    return rows, any_failed


def _print_summary(tool_rows, ds_install, oodle_dll, hzd_package, fw_package, fw_gamescript):
    print("\nDeciWaves setup summary:")
    print(f"  {'tool':<10} {'status':<32} path")
    for label, status, p in tool_rows:
        print(f"  {label:<10} {status:<32} {p}")
    print(f"  {'ds_install':<10} {'ok' if ds_install else '--':<32} {ds_install or '(not set)'}")
    print(f"  {'oodle_dll':<10} {'ok' if oodle_dll else 'MISSING':<32} {oodle_dll or '(not found)'}")
    print(f"  {'hzd_pkg':<10} {'ok' if hzd_package else '--':<32} {hzd_package or '(not set)'}")
    print(f"  {'fw_pkg':<10} {'ok' if fw_package else '--':<32} {fw_package or '(not set)'}")
    print(f"  {'fw_script':<10} {'ok' if fw_gamescript else '--':<32} {fw_gamescript or '(not set -- optional, BYO)'}")


def run_setup(argv) -> int:
    ap = argparse.ArgumentParser(prog="deciwaves setup", description=__doc__)
    # default=None (not "") for the path flags so an EXPLICIT empty string is
    # distinguishable from an omitted flag: omitted keeps the saved value,
    # `--flag ""` CLEARS it (finding 4 -- the only CLI recovery from a stale
    # ds_install/fw_gamescript that would otherwise make `doctor` exit 1 forever).
    ap.add_argument("--ds-install", default=None,
                    help="DS:DC game root (contains ds.exe, oo2core_7_win64.dll); "
                         'pass "" to clear a previously saved path')
    ap.add_argument("--hzd-package", default=None,
                    help='HZD Remastered .package/install path; pass "" to clear')
    ap.add_argument("--fw-package", default=None,
                    help='Forbidden West install/package path; pass "" to clear')
    ap.add_argument("--fw-gamescript", default=None, help="path to your own Forbidden West gamescript "
                    "transcript (BYO, optional -- see docs/BYO.md); needed for `fw run` to reach "
                    'match/full-reel/render without passing --gamescript every time; pass "" to clear')
    ap.add_argument("--tools-dir", default=None, help="where to fetch vgmstream/VGAudio/ffmpeg (default: %%LOCALAPPDATA%%\\DeciWaves\\tools)")
    ap.add_argument("--skip-downloads", action="store_true", help="don't fetch tools, just re-check what's already there and rewrite config")
    ap.add_argument("--force", action="store_true", help="re-download a tool even if its exe is already present in --tools-dir (default: skip it)")
    args = ap.parse_args(argv)

    # Merge this run's flags over whatever was already saved -- an omitted
    # flag means "keep what I had", so registering one game never blanks
    # another game's previously-configured paths (issue #36). A corrupted
    # config.json is already handled by config.load() (returns {} plus a
    # warning), so this merge degrades gracefully to "just this run's flags"
    # in that case too.
    saved = config.load()
    # Merge rule per key (finding 4): args.X is None -> keep saved; args.X == ""
    # -> CLEAR; else -> use args.X. Then resolve to absolute (issue #32) --
    # `saved`'s own values are already absolute from a prior run, so re-resolving
    # is a no-op; only a freshly-given relative flag changes shape, and "" stays
    # "" (an unset field).
    def _merged(arg_val, saved_val):
        return _resolve_or_empty(saved_val if arg_val is None else arg_val)

    ds_install = _merged(args.ds_install, saved.get("ds_install", ""))
    hzd_package = _merged(args.hzd_package, saved.get("hzd_package", ""))
    fw_package = _merged(args.fw_package, saved.get("fw_package", ""))
    fw_gamescript = _merged(args.fw_gamescript, saved.get("fw_gamescript", ""))
    tools_dir = (
        Path(args.tools_dir).resolve() if args.tools_dir
        else Path(saved["tools_dir"]).resolve() if saved.get("tools_dir")
        else _default_tools_dir()
    )
    tools_dir.mkdir(parents=True, exist_ok=True)

    tool_rows, tools_failed = _fetch_tools(tools_dir, args.skip_downloads, args.force)

    # Recomputed (not merely carried forward) from the merged ds_install so a
    # DS install that moved, or gained/lost the Oodle DLL since last run, is
    # reflected -- while an unrelated run (e.g. registering HZD only) still
    # sees the same ds_install and therefore the same oodle_dll.
    oodle_dll = _find_oodle(ds_install)
    if ds_install and not oodle_dll:
        print(f"WARNING: {OODLE_DLL_NAME} not found under {ds_install!r}. "
              f"Point --ds-install at the DS:DC game root -- the folder that directly "
              f"contains {OODLE_DLL_NAME}, alongside ds.exe.")

    hzd_warning = _hzd_package_warning(hzd_package)
    if hzd_warning:
        print(hzd_warning)

    if not (ds_install or hzd_package or fw_package):
        print("No game install configured (pass --ds-install / --hzd-package / --fw-package). "
              "Tools are set up regardless -- rerun `deciwaves setup` with a game path once you "
              "have one, or check status anytime with `deciwaves doctor`.")

    _print_summary(tool_rows, ds_install, oodle_dll, hzd_package, fw_package, fw_gamescript)

    config.save({
        "tools_dir": str(tools_dir),
        "ds_install": ds_install,
        "hzd_package": hzd_package,
        "fw_package": fw_package,
        "oodle_dll": oodle_dll,
        "fw_gamescript": fw_gamescript,
    })
    print(f"\nWrote {config.path()}")
    return 1 if tools_failed else 0


def main(argv=None) -> int:
    return run_setup(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
