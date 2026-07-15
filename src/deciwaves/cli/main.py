"""DeciWaves — voice-audio extraction for Decima-engine games you own."""
import argparse
import importlib
import os
import sys
from pathlib import Path

from deciwaves import __version__
from deciwaves.cli import config

STAGES = {
    "ds": {
        "catalog":   ("deciwaves.engine.catalog",           "Build the line catalog from your install"),
        "cutscenes": ("deciwaves.games.ds.cutscene_audio",  "Resolve cutscene voice tracks"),
        "trim":      ("deciwaves.games.ds.cutscene_trim",   "[GPU] Rebuild the speech-trim manifest"),
        "order":     ("deciwaves.engine.story_order",       "Build the story-ordered playlist"),
        "render":    ("deciwaves.engine.render",             "Render MP3 reels + tracklists"),
    },
    "hzd": {
        "catalog":      ("deciwaves.games.hzd.catalog",      "Build the line catalog"),
        "clip-index":   ("deciwaves.games.hzd.clip_index",   "Fingerprint audio clips"),
        "wem-metadata": ("deciwaves.games.hzd.wem_metadata", "Extract wem metadata + coverage"),
        "bind":         ("deciwaves.games.hzd.asr_bind",     "[GPU] Bind clips to lines"),
        "render":       ("deciwaves.games.hzd.render",       "Render MP3 reels + tracklists"),
    },
    "fw": {
        "extract":       ("deciwaves.games.fw.extract",        "Extract dialogue clips to WAV"),
        "asr":           ("deciwaves.games.fw.asr_run",        "[GPU] Transcribe clips"),
        "subtitle-bind": ("deciwaves.games.fw.subtitle_bind",  "Label clips with exact subtitles"),
        "match":         ("deciwaves.games.fw.subtitle_match", "Speaker + story order (needs BYO gamescript)"),
        "full-reel":     ("deciwaves.games.fw.story_full",     "Assemble the full-reel manifest"),
        "weave":         ("deciwaves.games.fw.weave",          "Woven story manifest"),
        "dlc":           ("deciwaves.games.fw.dlc",            "Burning Shores manifest"),
        "assemble":      ("deciwaves.games.fw.assemble",       "Concatenate manifests"),
        "render":        ("deciwaves.games.fw.render",         "Render MP3 reels + tracklists"),
    },
}

def _import_stage(module_name):
    return importlib.import_module(module_name).main

def _apply_config_env():
    cfg = config.load()
    if cfg.get("tools_dir") and os.path.isdir(cfg["tools_dir"]):
        os.environ["PATH"] = cfg["tools_dir"] + os.pathsep + os.environ.get("PATH", "")
        for exe, var in (("vgmstream-cli.exe", "DECIWAVES_VGMSTREAM"),
                         ("VGAudioCli.exe", "DECIWAVES_VGAUDIO")):
            p = Path(cfg["tools_dir"]) / exe
            if p.is_file():
                os.environ.setdefault(var, str(p))
    return cfg

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="deciwaves", description=__doc__)
    ap.add_argument("--version", action="version", version=f"deciwaves {__version__}")
    ap.add_argument("--workspace", default=".", help="directory outputs are written under (default: current dir)")
    sub = ap.add_subparsers(dest="cmd", required=False)
    for name in ("setup", "doctor"):
        sub.add_parser(name, add_help=False)
    game_parsers = {}
    for game, stages in STAGES.items():
        gp = sub.add_parser(game)
        stage_names = (*stages, "run")
        # nargs=REMAINDER so a stage name -- "run" especially -- plus ALL of its
        # own following argv (including a "--help") is captured as one opaque
        # block, instead of gp's own default -h/--help intercepting a "--help"
        # meant for the stage's (or run's) own parser. Without this, argparse's
        # subparsers hand gp the whole remaining token stream, gp's own --help
        # matches "--help" wherever it falls in that stream, and fires before
        # `args.stage` is ever inspected below -- see issue #8. A bare
        # `deciwaves <game> --help` (no stage token first) is unaffected: gp's
        # own --help still fires immediately in that case (nothing to consume
        # ahead of it), so the generic stage-list help below still works.
        gp.add_argument("stage", nargs=argparse.REMAINDER,
                         metavar="{%s}" % ",".join(stage_names),
                         help="stage to run, plus that stage's own arguments")
        game_parsers[game] = gp
    try:
        args, rest = ap.parse_known_args(argv)
    except SystemExit as e:
        # argparse raises SystemExit both for "clean" exits (--version / --help,
        # code 0) and for usage errors (unknown subcommand/stage, code 2). The
        # --version test expects the former to propagate as a real SystemExit;
        # subcommand/stage errors should make main() *return* 2 instead, so
        # callers (and Task 9's `run`) can handle a bad invocation without a
        # try/except. Code 0 is the "nothing went wrong, just exiting" case --
        # let it propagate; anything else is a usage error we convert to a
        # return value.
        if not e.code:
            raise
        return e.code

    cfg = _apply_config_env()  # must run before any stage module import -- see
    # engine/audio_clip.py, games/fw/extract.py, games/hzd/atrac9.py: their tool
    # path constants (VGMSTREAM/VGAUDIO) are resolved at import time from the env
    # this call sets up.
    if args.cmd is None:
        from deciwaves.cli.guided import run_guided; return run_guided(cfg)
    if args.cmd == "setup":
        from deciwaves.cli.setup import run_setup; return run_setup(rest)
    if args.cmd == "doctor":
        from deciwaves.cli.doctor import run_doctor; return run_doctor(rest)

    # args.stage is the REMAINDER list captured above: the stage name plus that
    # stage's own argv. REMAINDER doesn't support argparse `choices` validation
    # (it "converts all values, checking none" -- see argparse's _get_values),
    # so validate the stage name ourselves, the same way gp's own choices error
    # used to (unknown-stage exit code 2, see test_unknown_stage_errors).
    stage_argv = args.stage
    valid_stages = (*STAGES[args.cmd], "run")
    if not stage_argv or stage_argv[0] not in valid_stages:
        gp = game_parsers[args.cmd]
        try:
            if not stage_argv:
                gp.error("the following arguments are required: stage")
            else:
                gp.error(f"argument stage: invalid choice: {stage_argv[0]!r} "
                         f"(choose from {', '.join(repr(v) for v in valid_stages)})")
        except SystemExit as e:
            return e.code
    stage, extra_argv = stage_argv[0], stage_argv[1:] + rest

    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    os.chdir(ws)                      # stage modules default outputs to CWD-relative out/
    if stage == "run":
        from deciwaves.cli.run import run_game; return run_game(args.cmd, cfg, extra_argv)
    mod, _help = STAGES[args.cmd][stage]
    return _import_stage(mod)(extra_argv) or 0

if __name__ == "__main__":
    raise SystemExit(main())
