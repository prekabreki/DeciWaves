"""DeciWaves -- voice-audio extraction for Decima-engine games you own."""
import argparse
import importlib
import os
import sys
from pathlib import Path

from deciwaves import __version__
from deciwaves.cli import config

STAGES = {
    "ds": {
        "catalog":   ("deciwaves.games.ds.catalog",         "Build the line catalog from your install"),
        "cutscenes": ("deciwaves.games.ds.cutscene_audio",  "Resolve cutscene voice tracks"),
        "trim":      ("deciwaves.games.ds.cutscene_trim",   "[GPU] Rebuild the speech-trim manifest"),
        "order":     ("deciwaves.games.ds.story_order",     "Build the story-ordered playlist"),
        "dump":      ("deciwaves.games.ds.dump",      "Decode selected lines to WAV files"),
        "render":    ("deciwaves.games.ds.render",       "Render MP3 reels + tracklists"),
    },
    "hzd": {
        "catalog":      ("deciwaves.games.hzd.catalog",      "Build the line catalog"),
        "clip-index":   ("deciwaves.games.hzd.clip_index",   "Fingerprint audio clips"),
        "wem-metadata": ("deciwaves.games.hzd.wem_metadata", "Extract wem metadata + coverage"),
        "bind":         ("deciwaves.games.hzd.asr_bind",     "[GPU] Bind clips to lines"),
        "dump":         ("deciwaves.games.hzd.dump",         "Decode selected clips to WAV"),
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
        "dump":          ("deciwaves.games.fw.dump",           "Copy selected WAVs to output dir"),
        "render":        ("deciwaves.games.fw.render",         "Render MP3 reels + tracklists"),
    },
}

def _import_stage(module_name):
    return importlib.import_module(module_name).main


def _dispatch(fn, *args):
    """Call ``fn(*args)``, converting a usage-error ``SystemExit`` (nonzero
    code) into a plain return value instead of letting it propagate.

    Mirrors the "usage errors return 2" contract this module's own
    top-level parser and invalid-stage-name handling already apply to
    themselves (see the two other ``except SystemExit`` blocks in
    ``main()``) -- but a dispatched target's OWN internal
    ``argparse.parse_args`` call (doctor's, setup's, or any stage module's)
    used to bypass that contract entirely and raise a raw ``SystemExit``
    straight out of ``main()`` (issue #33). A clean ``--help``/``--version``
    exit (code 0, or no code at all) still propagates as a real
    ``SystemExit`` -- only an error code gets swallowed into a return value.
    """
    try:
        return fn(*args)
    except SystemExit as e:
        if not e.code:
            raise
        return e.code

def _stage_choices(game: str) -> tuple:
    """A game's stage names plus the synthetic `run` stage (STAGES doesn't list
    it -- it's handled separately below, dispatching to cli.run instead of a
    STAGES module). Used both for the REMAINDER metavar and for validating
    args.stage, so the two stay in sync."""
    return (*STAGES[game], "run")

def _stage_list_epilog(game: str) -> str:
    """Render STAGES[game]'s curated per-stage help_text as `deciwaves <game>
    --help`'s epilog. These strings used to be dead data -- STAGES[game][stage]
    is a (module_path, help_text) pair, but the only place that ever read it
    (main()'s dispatch, below) discarded help_text into a `_help` throwaway
    and used just the module path (issue #32). Surfacing them here is the fix:
    a stage's one-line description is now genuinely user-visible, not just a
    comment-shaped string sitting in a dict."""
    width = max(len(name) for name in _stage_choices(game))
    lines = [f"  {name:<{width}}  {help_text}" for name, (_mod, help_text) in STAGES[game].items()]
    lines.append(f"  {'run':<{width}}  chain {game}'s stages end-to-end (see `deciwaves {game} run --help`)")
    return "stages:\n" + "\n".join(lines)

def _gui_is_available() -> bool:
    """Thin indirection over gui.is_available() so dispatch is patchable in tests
    without a real PySide6 install (issue #67)."""
    from deciwaves import gui
    return gui.is_available()

def _apply_config_env():
    # Shared with the GUI launch path (see config.apply_tool_env / gui.launch, issue #71) so
    # the decode tools resolve no matter which console-script started the process.
    return config.apply_tool_env()

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="deciwaves", description=__doc__)
    ap.add_argument("--version", action="version", version=f"deciwaves {__version__}")
    ap.add_argument("--debug", action="store_true", help=(
        "re-raise an unhandled error so the full traceback prints (instead of "
        "a one-line message); also enabled by DECIWAVES_DEBUG=1. Must come "
        "BEFORE the game name, like --workspace -- after it, the token is "
        "swallowed as that stage's own argument instead."
    ))
    ap.add_argument("--workspace", default=".", help=(
        "directory outputs are written under (default: current dir). Must come "
        "BEFORE the game name, e.g. `deciwaves --workspace DIR ds run` -- placed "
        "after it (`deciwaves ds --workspace DIR run`), it is swallowed as that "
        "stage's own argument instead, not read as the global --workspace. A "
        "relative path you pass to a known path-taking flag (e.g. --gamescript) "
        "that ALREADY EXISTS there is resolved against the directory you ran "
        "`deciwaves` from, before the process chdirs into --workspace -- it does "
        "not need to sit inside the workspace (a path that doesn't exist yet, "
        "e.g. a stage's own output flag, is left alone and stays "
        "workspace-relative, same as always). A path saved via `deciwaves setup` "
        "is always stored absolute, so it is unaffected by --workspace either way."
    ))
    sub = ap.add_subparsers(dest="cmd", required=False)
    for name in ("setup", "doctor", "gui"):
        sub.add_parser(name, add_help=False)
    game_parsers = {}
    for game, stages in STAGES.items():
        gp = sub.add_parser(game, epilog=_stage_list_epilog(game),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
        stage_names = _stage_choices(game)
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

    try:
        return _main_dispatch(args, rest, game_parsers)
    except Exception as exc:
        # An unhandled error from a dispatched target -- or anything else in the
        # pipeline -- must not land as a raw traceback: the GUI runs the child
        # with QProcess.MergedChannels, so a traceback would be the primary
        # error UI (issue #297). Report one human line on stderr and a nonzero
        # exit code; --debug / DECIWAVES_DEBUG=1 re-raises for the full
        # traceback. KeyboardInterrupt and SystemExit are BaseException
        # subclasses and deliberately pass through uncaught.
        if args.debug or os.environ.get("DECIWAVES_DEBUG") == "1":
            raise
        detail = str(exc) or type(exc).__name__
        print(f"deciwaves: error: {detail} -- re-run with --debug "
              f"(or DECIWAVES_DEBUG=1) for the full traceback", file=sys.stderr)
        return 1


def _main_dispatch(args, rest, game_parsers) -> int:
    """The work main() routes to after parsing: apply the config env, resolve
    and enter the workspace, then hand off to the GUI / guided prompt / setup /
    doctor / a single game stage / `run`. Split out of main() so main() can
    wrap it in one top-level ``except Exception`` (issue #297: an unhandled
    error from a stage must be a one-line stderr message plus a nonzero exit
    code, not a raw traceback)."""
    cfg = _apply_config_env()  # sets DECIWAVES_VGMSTREAM/DECIWAVES_VGAUDIO (and
    # PATH) from saved config; engine.tool_paths.resolve() reads them when the
    # decoder subprocess is actually spawned, not at stage-module import time.
    if args.cmd is None:
        # Bare `deciwaves`: the GUI is the primary interface (issue #67), so launch it
        # when the [gui] extra is importable; otherwise fall back to today's guided
        # prompt with a one-line install hint.
        if _gui_is_available():
            from deciwaves import gui
            return gui.launch(rest)
        # Resolve to an absolute path before handing it to guided mode as its
        # workspace-prompt default -- whether it came from an explicit
        # --workspace or is just the "." argparse default, the prompt should
        # always show a real absolute path, matching what it showed before
        # this flag existed (issue #32: bare `deciwaves --workspace X` used
        # to silently ignore --workspace entirely here, always defaulting the
        # prompt to Path.cwd() instead).
        from deciwaves.cli.guided import run_guided
        from deciwaves import gui
        print(f"(tip: install the desktop GUI -- {gui.INSTALL_HINT})")
        return run_guided(cfg, workspace=str(Path(args.workspace).resolve()))
    if args.cmd == "setup":
        from deciwaves.cli.setup import run_setup; return _dispatch(run_setup, rest)
    if args.cmd == "doctor":
        from deciwaves.cli.doctor import run_doctor; return _dispatch(run_doctor, rest)
    if args.cmd == "gui":
        # gui.launch() owns the availability check and INSTALL_HINT (issue #308) --
        # the subcommand just delegates, so the hint is printed from exactly one place.
        from deciwaves import gui
        return gui.launch(rest)

    # args.stage is the REMAINDER list captured above: the stage name plus that
    # stage's own argv. REMAINDER doesn't support argparse `choices` validation
    # (it "converts all values, checking none" -- see argparse's _get_values),
    # so validate the stage name ourselves, the same way gp's own choices error
    # used to (unknown-stage exit code 2, see test_unknown_stage_errors).
    stage_argv = args.stage
    valid_stages = _stage_choices(args.cmd)
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

    # Absolutize any relative path in the stage's own argv (e.g. --gamescript)
    # BEFORE chdir'ing into --workspace -- otherwise a relative flag value is
    # silently looked up inside the workspace instead of relative to wherever
    # the user actually ran `deciwaves` from (issue #32). Passing args.workspace
    # through lets absolutize_existing_paths tell "no workspace given" (or a
    # workspace that's just cwd again) apart from a genuinely different one --
    # only the latter can leave a token ambiguous between the two (issue #44).
    # A resulting SystemExit(2) (ambiguous between cwd and --workspace) is
    # converted to a return, same "usage errors return 2" contract as this
    # function's other SystemExit catches above -- no stage runs.
    try:
        extra_argv = config.absolutize_existing_paths(extra_argv, workspace=args.workspace, game=args.cmd, stage=stage)
    except SystemExit as e:
        return e.code
    config.enter_workspace(args.workspace)
    if stage == "run":
        from deciwaves.cli.run import run_game; return _dispatch(run_game, args.cmd, cfg, extra_argv)
    mod, _help = STAGES[args.cmd][stage]
    return _dispatch(lambda: _import_stage(mod)(extra_argv) or 0)

if __name__ == "__main__":
    raise SystemExit(main())
