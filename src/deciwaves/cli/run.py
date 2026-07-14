"""``deciwaves <game> run`` — chain a game's stages end-to-end, with resume + gating.

Deliberately dumb and explicit (YAGNI): a :class:`Stage` is a name, its STAGES module
string, a function that builds that stage's argv from a small per-game context dict,
and the workspace-relative path/dir that marks it done. The loop is a plain
for-loop -- no plugin machinery, no stage discovery magic.

Per-game chains (see task-9 brief):
    ds:  catalog -> cutscenes -> order -> render
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
    primary_output: str
    gpu: bool = False  # gate on importlib.util.find_spec("whisperx") before running


def _gpu_gate_message(stage_name: str) -> str:
    return (f"{stage_name}: needs the GPU ASR extra -- install it with "
            f"`pip install deciwaves[asr]`, plus PyTorch for your CUDA version "
            f"(see https://pytorch.org/get-started/locally/).")


def _run_chain(chain: list[Stage], ctx: dict) -> int:
    for st in chain:
        if os.path.exists(st.primary_output):
            print(f"skip {st.name} ({st.primary_output} exists — delete it to re-run)")
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


def _ds_cutscenes_argv(ctx: dict) -> list:
    return ["--data-dir", ctx["data_dir"], "--oodle", ctx["oodle"]]


def _ds_order_argv(ctx: dict) -> list:
    return []


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
    chain = [
        Stage("catalog", STAGES["ds"]["catalog"][0], _ds_catalog_argv, "out/catalog.csv"),
        Stage("cutscenes", STAGES["ds"]["cutscenes"][0], _ds_cutscenes_argv, "out/cutscene_tracks.csv"),
        Stage("order", STAGES["ds"]["order"][0], _ds_order_argv, "out/playlist.csv"),
        Stage("render", STAGES["ds"]["render"][0], _ds_render_argv, "out/audio"),
    ]
    return _run_chain(chain, ctx)


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
        Stage("catalog", STAGES["hzd"]["catalog"][0], _hzd_package_argv, "out/hzd/catalog.csv"),
        Stage("clip-index", STAGES["hzd"]["clip-index"][0], _hzd_package_argv, "out/hzd/clip-index.csv"),
        Stage("wem-metadata", STAGES["hzd"]["wem-metadata"][0], _hzd_package_argv, "out/hzd/wem-metadata.csv"),
        Stage("bind", STAGES["hzd"]["bind"][0], _hzd_package_argv, "out/hzd/asr-manifest.csv", gpu=True),
        Stage("render", STAGES["hzd"]["render"][0], _hzd_package_argv, "out/hzd/audio"),
    ]
    return _run_chain(chain, ctx)


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
        Stage("extract", STAGES["fw"]["extract"][0], _fw_extract_argv, "out/fw"),
        Stage("asr", STAGES["fw"]["asr"][0], _fw_asr_argv, "out/fw/transcripts.csv", gpu=True),
        Stage("subtitle-bind", STAGES["fw"]["subtitle-bind"][0], _fw_subtitle_bind_argv,
              _FW_SUBTITLE_MANIFEST_FULL),
    ]
    rc = _run_chain(chunk1, ctx)
    if rc:
        return rc

    gamescript = ctx["gamescript"]
    if not gamescript or not os.path.isfile(gamescript):
        print(_FW_BYO_MESSAGE)
        return 0

    chunk2 = [
        Stage("match", STAGES["fw"]["match"][0], _fw_match_argv, "out/fw/story-manifest.csv"),
        Stage("full-reel", STAGES["fw"]["full-reel"][0], _fw_full_reel_argv, _FW_FULL_REEL_MANIFEST),
        Stage("render", STAGES["fw"]["render"][0], _fw_render_argv, "out/fw/audio"),
    ]
    return _run_chain(chunk2, ctx)


# ---------------------------------------------------------------------------

_RUNNERS = {"ds": _run_ds, "hzd": _run_hzd, "fw": _run_fw}


def run_game(game: str, cfg: dict, extra_argv: list) -> int:
    runner = _RUNNERS.get(game)
    if runner is None:
        print(f"deciwaves: unknown game {game!r}")
        return 2
    return runner(cfg, extra_argv)
