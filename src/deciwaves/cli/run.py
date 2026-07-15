"""``deciwaves <game> run`` — chain a game's stages end-to-end, with resume + gating.

Deliberately dumb and explicit (YAGNI): a :class:`Stage` is a name, its STAGES module
string, and a function that builds that stage's argv from a small per-game context
dict. The loop is a plain for-loop -- no plugin machinery, no stage discovery magic.

Resume is driven by a per-stage done-marker file, ``out/<game>/.done-<stage>``,
written only after a stage's ``main()`` returns rc==0. A stage's own output path or
directory existing is NOT a skip criterion: a stage's own mkdir (or a leftover
output from an old build) must not look like "done", and one stage's output
directory must never be mistaken for another stage's (see issues #15 and #6).

Per-game chains (see task-9 brief):
    ds:  catalog -> order -> render (cutscene voice tracks come from the packaged,
         pre-resolved ds/cutscene_tracks.csv -- the `cutscenes` stage is NOT part of
         the default chain; it remains available standalone via `deciwaves ds
         cutscenes` for users who want to regenerate it against their own install)
    hzd: catalog -> clip-index -> wem-metadata -> bind[GPU] -> render
    fw:  extract -> asr[GPU] -> subtitle-bind -- (BYO gamescript gate) --
         match -> full-reel -> render
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from dataclasses import dataclass
from typing import Callable

from deciwaves import data
from deciwaves.cli.main import STAGES, _import_stage  # noqa: F401 -- re-exported for monkeypatching


class StageConfigError(Exception):
    """Raised by a Stage's build_argv when it can't assemble its argv (e.g. a
    packaged data file this build doesn't bundle yet). Turned into a clean
    stage failure by the run loop instead of an uncaught traceback."""


@dataclass(frozen=True)
class Stage:
    name: str
    module: str
    build_argv: Callable[[dict], list]
    gpu: bool = False  # gate on importlib.util.find_spec("whisperx") before running


def _gpu_gate_message(stage_name: str) -> str:
    return (f"{stage_name}: needs the GPU ASR extra -- install it with "
            f"`pip install deciwaves[asr]`, plus PyTorch for your CUDA version "
            f"(see https://pytorch.org/get-started/locally/).")


def _done_marker(game: str, stage_name: str) -> str:
    """Workspace-relative path to a stage's done-marker (issues #15, #6).

    A stage is considered done iff this file exists -- never its own output
    path/directory, which can pre-exist from a crash after mkdir, a leftover
    from an old build, or (for fw) another stage entirely.
    """
    return os.path.join("out", game, f".done-{stage_name}")


def _run_chain(game: str, chain: list[Stage], ctx: dict) -> int:
    for st in chain:
        marker = _done_marker(game, st.name)
        if os.path.isfile(marker):
            print(f"skip {st.name} ({marker} exists -- delete it to force a re-run)")
            continue
        if st.gpu and importlib.util.find_spec("whisperx") is None:
            print(_gpu_gate_message(st.name))
            return 1
        try:
            argv = st.build_argv(ctx)
        except StageConfigError as exc:
            print(f"{st.name}: {exc}")
            return 1
        rc = _import_stage(st.module)(argv) or 0
        if rc:
            return rc
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        open(marker, "w", encoding="utf-8").close()
    return 0


def _missing_config(game: str, hint: str, flag_hint: str) -> int:
    print(f"deciwaves {game} run: no {hint} configured -- run `deciwaves setup` first, "
          f"or pass {flag_hint} explicitly.")
    return 1


# ---------------------------------------------------------------------------
# ds
# ---------------------------------------------------------------------------

def _ds_catalog_argv(ctx: dict) -> list:
    argv = ["--data-dir", ctx["data_dir"], "--oodle", ctx["oodle"]]
    try:
        file_list = data.packaged("ds/data-file-list.txt")
    except FileNotFoundError as exc:
        raise StageConfigError(
            "ds/data-file-list.txt isn't bundled in this build yet (predates the "
            "packaged file-list) -- pass --file-list explicitly to `deciwaves ds "
            "catalog`, or rebuild once it's bundled."
        ) from exc
    return argv + ["--file-list", str(file_list)]


def _ds_order_argv(ctx: dict) -> list:
    try:
        cutscene_tracks = data.packaged("ds/cutscene_tracks.csv")
    except FileNotFoundError as exc:
        raise StageConfigError(
            "ds/cutscene_tracks.csv isn't bundled in this build yet (predates the "
            "packaged cutscene tracks) -- run `deciwaves ds cutscenes` yourself and "
            "pass --cutscene-tracks explicitly to `deciwaves ds order`, or rebuild "
            "once it's bundled."
        ) from exc
    return ["--cutscene-tracks", str(cutscene_tracks)]


def _ds_render_argv(ctx: dict) -> list:
    try:
        keepspans = data.packaged("ds/cutscene-keepspans.csv")
    except FileNotFoundError as exc:
        raise StageConfigError(
            "ds/cutscene-keepspans.csv isn't bundled in this build yet -- pass "
            "--speech-trim explicitly to `deciwaves ds render`, or rebuild once "
            "it's bundled."
        ) from exc
    return ["--data-dir", ctx["data_dir"], "--oodle", ctx["oodle"],
            "--main-story", "--speech-trim", str(keepspans), "--bitrate", "96"]


def _run_ds(cfg: dict, extra_argv: list) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--data-dir")
    ap.add_argument("--oodle")
    ns, _ = ap.parse_known_args(extra_argv)

    ds_install = cfg.get("ds_install")
    data_dir = ns.data_dir or (os.path.join(ds_install, "data") if ds_install else None)
    oodle = (ns.oodle or cfg.get("oodle_dll")
             or (os.path.join(ds_install, "oo2core_7_win64.dll") if ds_install else None))
    if not data_dir or not oodle:
        return _missing_config("ds", "DS install (ds_install)", "--data-dir/--oodle")

    ctx = {"data_dir": data_dir, "oodle": oodle}
    # No "cutscenes" stage here: the default chain uses the bundled, pre-resolved
    # ds/cutscene_tracks.csv (see _ds_order_argv) instead of regenerating it against
    # the user's install. `deciwaves ds cutscenes` remains available standalone for
    # anyone who wants to regenerate it (e.g. against a patched install).
    chain = [
        Stage("catalog", STAGES["ds"]["catalog"][0], _ds_catalog_argv),
        Stage("order", STAGES["ds"]["order"][0], _ds_order_argv),
        Stage("render", STAGES["ds"]["render"][0], _ds_render_argv),
    ]
    return _run_chain("ds", chain, ctx)


# ---------------------------------------------------------------------------
# hzd
# ---------------------------------------------------------------------------

def _hzd_package_argv(ctx: dict) -> list:
    return ["--package", ctx["package"]]


def _run_hzd(cfg: dict, extra_argv: list) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--package")
    ns, _ = ap.parse_known_args(extra_argv)

    package = ns.package or cfg.get("hzd_package")
    if not package:
        return _missing_config("hzd", "HZD package (hzd_package)", "--package")

    ctx = {"package": package}
    chain = [
        Stage("catalog", STAGES["hzd"]["catalog"][0], _hzd_package_argv),
        Stage("clip-index", STAGES["hzd"]["clip-index"][0], _hzd_package_argv),
        Stage("wem-metadata", STAGES["hzd"]["wem-metadata"][0], _hzd_package_argv),
        Stage("bind", STAGES["hzd"]["bind"][0], _hzd_package_argv, gpu=True),
        Stage("render", STAGES["hzd"]["render"][0], _hzd_package_argv),
    ]
    return _run_chain("hzd", chain, ctx)


# ---------------------------------------------------------------------------
# fw
# ---------------------------------------------------------------------------

_FW_BYO_MESSAGE = (
    "fw: no gamescript configured. extract/asr/subtitle-bind are done; speaker + "
    "story-order matching needs your own copy of the Forbidden West gamescript -- "
    "BYO, this repo can't ship game text. Re-run with --gamescript <path> to "
    "continue with match -> full-reel -> render."
)

# subtitle-bind's own --out default ("out/fw/subtitle-manifest.csv") is a quick-sample
# name; match/full-reel/weave all default to reading the "-full" name, so the run chain
# asks subtitle-bind to write that name directly rather than overriding three downstream
# defaults.
_FW_SUBTITLE_MANIFEST_FULL = "out/fw/subtitle-manifest-full.csv"
_FW_FULL_REEL_MANIFEST = "out/fw/full-reel-manifest.csv"


def _fw_extract_argv(ctx: dict) -> list:
    return ["--package", ctx["package"]]


def _fw_asr_argv(ctx: dict) -> list:
    return []


def _fw_subtitle_bind_argv(ctx: dict) -> list:
    return ["--package-dir", ctx["package"], "--out", _FW_SUBTITLE_MANIFEST_FULL]


def _fw_match_argv(ctx: dict) -> list:
    return ["--gamescript", ctx["gamescript"]]


def _fw_full_reel_argv(ctx: dict) -> list:
    return []


def _fw_render_argv(ctx: dict) -> list:
    return ["--manifest", _FW_FULL_REEL_MANIFEST,
            "--tiers", "1,2,S", "--stem", "fw_story_full", "--uniform-mono"]


def _run_fw(cfg: dict, extra_argv: list) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--package")
    ap.add_argument("--gamescript")
    ns, _ = ap.parse_known_args(extra_argv)

    package = ns.package or cfg.get("fw_package")
    if not package:
        return _missing_config("fw", "FW package (fw_package)", "--package")

    ctx = {"package": package, "gamescript": ns.gamescript}
    chunk1 = [
        Stage("extract", STAGES["fw"]["extract"][0], _fw_extract_argv),
        Stage("asr", STAGES["fw"]["asr"][0], _fw_asr_argv, gpu=True),
        Stage("subtitle-bind", STAGES["fw"]["subtitle-bind"][0], _fw_subtitle_bind_argv),
    ]
    rc = _run_chain("fw", chunk1, ctx)
    if rc:
        return rc

    gamescript = ctx["gamescript"]
    if not gamescript or not os.path.isfile(gamescript):
        print(_FW_BYO_MESSAGE)
        return 0

    chunk2 = [
        Stage("match", STAGES["fw"]["match"][0], _fw_match_argv),
        Stage("full-reel", STAGES["fw"]["full-reel"][0], _fw_full_reel_argv),
        Stage("render", STAGES["fw"]["render"][0], _fw_render_argv),
    ]
    return _run_chain("fw", chunk2, ctx)


# ---------------------------------------------------------------------------

_RUNNERS = {"ds": _run_ds, "hzd": _run_hzd, "fw": _run_fw}


def run_game(game: str, cfg: dict, extra_argv: list) -> int:
    runner = _RUNNERS.get(game)
    if runner is None:
        print(f"deciwaves: unknown game {game!r}")
        return 2
    return runner(cfg, extra_argv)
