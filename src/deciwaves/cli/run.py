"""``deciwaves <game> run`` — chain a game's stages end-to-end, with resume + gating.

Deliberately dumb and explicit (YAGNI): a :class:`Stage` is a name, its STAGES module
string, and a function that builds that stage's argv from a small per-game context
dict. The loop is a plain for-loop -- no plugin machinery, no stage discovery magic.

Resume is driven by a per-stage done-marker file, ``out/<game>/.done-<stage>``,
written only after a stage's ``main()`` returns rc==0. A stage's own output path or
directory existing is NOT a skip criterion: a stage's own mkdir (or a leftover
output from an old build) must not look like "done", and one stage's output
directory must never be mistaken for another stage's (see issues #15 and #6).

``--until <stage>`` runs the chain only through that stage (the GPU gate then only
considers stages inside the slice, so the pre-GPU stages run without the [asr]
extra); ``--from <stage>`` deletes that stage's marker before running, so it and
everything after it re-run. Together they are the GUI's Scan button and the stage
strip's "Re-run from here" (issue #62, docs/deciwaves-gui-spec.md §5.2).

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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from deciwaves import data
from deciwaves.cli.main import STAGES, _import_stage  # noqa: F401 -- re-exported for monkeypatching
from deciwaves.games.hzd import asr_bind


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


def _remove_marker(game: str, stage_name: str) -> None:
    """Delete a stage's done-marker, tolerating absence (never ran, or already
    invalidated). The single home of the delete-a-marker idiom, shared by
    cascade invalidation and --from -- marker semantics are load-bearing
    (issues #15/#6/#37), so there is exactly one implementation to get right."""
    try:
        os.remove(_done_marker(game, stage_name))
    except FileNotFoundError:
        pass


def _invalidate_downstream_markers(game: str, full_chain: list[Stage], stage_name: str) -> None:
    """Delete the done-markers of every stage that comes AFTER ``stage_name`` in
    the game's full declared chain (issue #37).

    Resume markers previously only ever skipped work -- nothing invalidated
    them, so re-running an early stage (e.g. re-cataloging after a game patch)
    left later stages' stale markers standing, and a stale run became
    indistinguishable from a fresh one. ``full_chain`` is the game's complete,
    declared stage order (not necessarily the same list object actually being
    executed in this call -- fw splits its chain across the BYO --gamescript
    gate into two separate `_run_chain` calls, so invalidation must still see
    the stages on the far side of that gate to find "later" correctly).
    """
    names = [s.name for s in full_chain]
    idx = names.index(stage_name)
    for later_name in names[idx + 1:]:
        _remove_marker(game, later_name)


def _blocking_gpu_stage(game: str, chain: list[Stage],
                        full_chain: list[Stage] | None = None) -> Stage | None:
    """The first GPU-gated stage in ``chain`` that WILL effectively run yet would
    fail for lack of the ASR extra, or ``None`` if none would.

    Used to scan the whole chain UPFRONT, before any stage runs, instead of
    discovering the gate mid-chain after earlier (possibly hours-long) stages
    already ran (issue #33).

    Crucially, the scan is invalidation-aware (finding 1): a GPU stage
    effectively runs not only when its OWN done-marker is absent, but also when
    ANY earlier stage in the full declared chain will run -- because that
    running stage deletes every downstream marker via
    ``_invalidate_downstream_markers`` before this GPU stage is reached, so its
    currently-present marker is about to vanish. Reasoning only about the GPU
    stage's own marker (as this used to) let the gate pass, catalog run for
    hours, and bind then die with a raw ModuleNotFoundError once the re-catalog
    invalidated .done-bind. ``full_chain`` is the complete declared order (fw
    splits its chain across the BYO --gamescript gate into two `_run_chain`
    calls, so "earlier stage will run" must still see stages before the split);
    it defaults to ``chain`` for single-call pipelines. Only a GPU stage that is
    actually part of ``chain`` (this call's slice) is returned.
    """
    if importlib.util.find_spec("whisperx") is not None:
        return None
    full_chain = chain if full_chain is None else full_chain
    chain_names = {s.name for s in chain}
    upstream_will_run = False
    for st in full_chain:
        own_absent = not os.path.isfile(_done_marker(game, st.name))
        effectively_runs = own_absent or upstream_will_run
        if st.gpu and effectively_runs and st.name in chain_names:
            return st
        if own_absent:
            upstream_will_run = True
    return None


def _run_chain(game: str, chain: list[Stage], ctx: dict, full_chain: list[Stage] | None = None) -> int:
    """Run ``chain`` in order, skipping stages whose done-marker already exists.

    ``full_chain`` is the game's complete declared stage order, used only to
    compute "later stages" for marker invalidation (see
    ``_invalidate_downstream_markers``); it defaults to ``chain`` itself for
    games whose whole pipeline runs through a single `_run_chain` call.

    The whole chain's GPU gate is checked upfront (see ``_blocking_gpu_stage``)
    before any stage runs -- so a missing ASR extra aborts immediately, not
    after wasting however long the earlier stages take.
    """
    full_chain = chain if full_chain is None else full_chain
    blocking = _blocking_gpu_stage(game, chain, full_chain)
    if blocking is not None:
        print(_gpu_gate_message(blocking.name))
        return 1
    for st in chain:
        marker = _done_marker(game, st.name)
        if os.path.isfile(marker):
            print(f"skip {st.name} ({marker} exists -- delete it to force a re-run)")
            continue
        try:
            argv = st.build_argv(ctx)
        except StageConfigError as exc:
            print(f"{st.name}: {exc}")
            return 1
        # The stage is genuinely about to (re-)execute -- its data may already
        # differ from what any later stage previously consumed, so invalidate
        # downstream markers now, before dispatch, so a failed run still
        # leaves them invalidated (they're stale either way).
        _invalidate_downstream_markers(game, full_chain, st.name)
        rc = _import_stage(st.module)(argv) or 0
        if rc:
            return rc
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        Path(marker).touch()
    return 0


def _add_slice_flags(ap: argparse.ArgumentParser, chain: list[Stage]) -> None:
    """--until/--from for a game's ``run`` parser (issue #62, GUI spec §5.2):
    the Scan-button and re-run-from-here primitives. ``choices`` doubles as
    validation and as the only place stage names are discoverable from --help."""
    names = [s.name for s in chain]
    ap.add_argument("--until", choices=names,
                    help="run the chain only up to and including this stage; "
                         "done-markers skip/invalidate as usual, and the GPU-extra "
                         "check only considers stages inside the slice (so the "
                         "pre-GPU stages run fine without deciwaves[asr])")
    ap.add_argument("--from", dest="from_stage", choices=names,
                    help="re-run from this stage: delete its done-marker before "
                         "running, so it re-executes (and later stages re-run too, "
                         "via the usual cascade invalidation); earlier stages "
                         "still skip via their own markers")


def _slice_bounds(game: str, chain: list[Stage], from_stage: str | None,
                  until_stage: str | None) -> tuple[int, int]:
    """Validate --from/--until against the declared chain (issue #62). Returns
    ``(last_idx, rc)``: a nonzero ``rc`` is a usage error (printed to stderr,
    the same stream as the parsers' own argparse errors) the caller must
    return; ``last_idx`` is the inclusive index into ``chain`` of the last
    stage --until keeps (the whole chain when --until wasn't given).

    Validation ONLY -- deleting --from's marker is the caller's own explicit
    follow-up (``_remove_marker``), so a run that fails validation here, or a
    game-specific gate checked after it (fw's gamescript gate), never deletes
    anything on its way out. Once the marker IS deleted, the chain runs
    normally, exactly like the manual delete-the-marker-and-re-run flow the
    skip message advertises: earlier stages still skip via their markers
    (never blind-skipped -- a missing earlier marker still resumes from
    there), and later stages re-run via cascade invalidation once the stage
    actually re-executes. Deleting before _run_chain also means the upfront
    GPU gate sees the stage as about-to-run, so `--from bind` without the
    [asr] extra aborts with the marker already deleted -- the same resumable
    state a manual delete leaves behind."""
    names = [s.name for s in chain]
    last_idx = names.index(until_stage) if until_stage else len(names) - 1
    if from_stage and names.index(from_stage) > last_idx:
        print(f"deciwaves {game} run: --from {from_stage} comes after "
              f"--until {until_stage} in the {game} chain "
              f"({' -> '.join(names)}) -- the re-run target would never "
              f"execute.", file=sys.stderr)
        return last_idx, 2
    return last_idx, 0


def _missing_config(game: str, hint: str, flag_hint: str) -> int:
    print(f"deciwaves {game} run: no {hint} configured -- run `deciwaves setup` first, "
          f"or pass {flag_hint} explicitly.")
    return 1


def _parse_or_exit(ap: argparse.ArgumentParser, extra_argv: list) -> argparse.Namespace | int:
    """Parse a per-game ``run`` parser's argv, mirroring cli.main.main()'s own
    "usage errors return 2" contract for its top-level parser: argparse raises
    SystemExit both for a clean exit (--help, code 0) and for a usage error
    (unknown/typo'd flag, code 2). Code 0 is "nothing went wrong, just exiting"
    -- let it propagate as a real SystemExit, so `--help` behaves like any other
    argparse CLI. A nonzero code is converted into a plain return value (an int,
    instead of a Namespace) so callers -- including `run_game()`'s own return
    value -- observe exit code 2 without needing a try/except.
    """
    try:
        return ap.parse_args(extra_argv)
    except SystemExit as exc:
        if not exc.code:
            raise
        return exc.code


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
    # No "cutscenes" stage here: the default chain uses the bundled, pre-resolved
    # ds/cutscene_tracks.csv (see _ds_order_argv) instead of regenerating it against
    # the user's install. `deciwaves ds cutscenes` remains available standalone for
    # anyone who wants to regenerate it (e.g. against a patched install).
    chain = [
        Stage("catalog", STAGES["ds"]["catalog"][0], _ds_catalog_argv),
        Stage("order", STAGES["ds"]["order"][0], _ds_order_argv),
        Stage("render", STAGES["ds"]["render"][0], _ds_render_argv),
    ]
    ap = argparse.ArgumentParser(
        prog="deciwaves ds run",
        description="Run the DS pipeline end-to-end: catalog -> order -> render.",
    )
    ap.add_argument("--data-dir", help="DS install's data directory (default: from `deciwaves setup`)")
    ap.add_argument("--oodle", help="path to oo2core_7_win64.dll (default: from `deciwaves setup`)")
    _add_slice_flags(ap, chain)
    ns = _parse_or_exit(ap, extra_argv)
    if isinstance(ns, int):
        return ns

    ds_install = cfg.get("ds_install")
    data_dir = ns.data_dir or (os.path.join(ds_install, "data") if ds_install else None)
    oodle = (ns.oodle or cfg.get("oodle_dll")
             or (os.path.join(ds_install, "oo2core_7_win64.dll") if ds_install else None))
    if not data_dir or not oodle:
        return _missing_config("ds", "DS install (ds_install)", "--data-dir/--oodle")

    ctx = {"data_dir": data_dir, "oodle": oodle}
    last_idx, rc = _slice_bounds("ds", chain, ns.from_stage, ns.until)
    if rc:
        return rc
    if ns.from_stage:
        _remove_marker("ds", ns.from_stage)  # --from's contract: delete, then run normally
    return _run_chain("ds", chain[:last_idx + 1], ctx, full_chain=chain)


# ---------------------------------------------------------------------------
# hzd
# ---------------------------------------------------------------------------

def _hzd_package_argv(ctx: dict) -> list:
    return ["--package", ctx["package"]]


def _hzd_bind_argv(ctx: dict) -> list:
    """bind's argv, PLUS --transcripts pointed at the sidecar's own default path when
    that file already exists (a crashed/interrupted prior bind run left it there).
    asr_bind.py's --transcripts loader already handles resuming from it (torn-row
    drop, tail heal, same-path append) -- this only decides *whether* to pass it,
    making the README's "an interrupted bind picks up where it stopped" claim true
    for the chained `hzd run` (previously only true for a manually-rerun `hzd bind`
    that passed --transcripts itself).

    Also forwards --sample-cap (issue #35) when the user gave one explicitly --
    ``ctx["sample_cap"]`` is ``None`` otherwise, in which case the flag is omitted
    entirely so bind falls back to its own bounded default (300). 0 is forwarded
    as-is (it's falsy but not None) -- asr_bind.py's own --sample-cap already
    treats 0 as "unlimited, run a full pass"."""
    argv = ["--package", ctx["package"]]
    if ctx.get("sample_cap") is not None:
        argv += ["--sample-cap", str(ctx["sample_cap"])]
    if os.path.isfile(asr_bind.DEFAULT_TRANSCRIPTS_OUT):
        argv += ["--transcripts", asr_bind.DEFAULT_TRANSCRIPTS_OUT]
    return argv


def _run_hzd(cfg: dict, extra_argv: list) -> int:
    chain = [
        Stage("catalog", STAGES["hzd"]["catalog"][0], _hzd_package_argv),
        Stage("clip-index", STAGES["hzd"]["clip-index"][0], _hzd_package_argv),
        Stage("wem-metadata", STAGES["hzd"]["wem-metadata"][0], _hzd_package_argv),
        Stage("bind", STAGES["hzd"]["bind"][0], _hzd_bind_argv, gpu=True),
        Stage("render", STAGES["hzd"]["render"][0], _hzd_package_argv),
    ]
    ap = argparse.ArgumentParser(
        prog="deciwaves hzd run",
        description="Run the HZD pipeline end-to-end: catalog -> clip-index -> "
                    "wem-metadata -> bind -> render.",
    )
    ap.add_argument("--package", help="HZD package/install path (default: from `deciwaves setup`)")
    ap.add_argument("--sample-cap", type=int, default=None,
                     help="forwarded to the bind stage: caps how many ambiguous "
                          "fingerprint-collision buckets get ASR-transcribed (default: "
                          "bind's own bounded default, 300 -- structural binding already "
                          "resolves most rows without any ASR). 0 = unlimited (an "
                          "uncapped full pass over every ambiguous bucket, hours on a full "
                          "library). NOTE: if `bind` already completed in this workspace, "
                          "passing a different --sample-cap here has no effect until you "
                          "delete out/hzd/.done-bind and re-run -- the done-marker doesn't "
                          "know its own flags changed.")
    _add_slice_flags(ap, chain)
    ns = _parse_or_exit(ap, extra_argv)
    if isinstance(ns, int):
        return ns

    package = ns.package or cfg.get("hzd_package")
    if not package:
        return _missing_config("hzd", "HZD package (hzd_package)", "--package")

    ctx = {"package": package, "sample_cap": ns.sample_cap}
    last_idx, rc = _slice_bounds("hzd", chain, ns.from_stage, ns.until)
    if rc:
        return rc
    if ns.from_stage:
        _remove_marker("hzd", ns.from_stage)  # --from's contract: delete, then run normally
    return _run_chain("hzd", chain[:last_idx + 1], ctx, full_chain=chain)


# ---------------------------------------------------------------------------
# fw
# ---------------------------------------------------------------------------

def _quoted_package(package: str) -> str:
    """Quote the package path when it contains a space so a suggested re-run
    command stays copy-pasteable (a real FW install lives under "...\\Forbidden
    West\\...") (finding 10). Spaceless paths (e.g. the "PKG" test placeholder)
    stay bare."""
    return f'"{package}"' if package and " " in package else package


def _fw_byo_message(package: str) -> str:
    """The BYO stop message printed when neither an explicit --gamescript nor a
    configured fw_gamescript was found (issue #23: the message must show the
    EXACT re-run command, not just a generic "pass --gamescript" hint, so guided
    mode's primary UX has something concrete to act on). ``package`` is filled in
    for real (it's whatever this run actually used, whether from --package or
    from the configured fw_package) since a re-run needs it too; the gamescript
    path itself stays a placeholder -- it's BYO, this repo never has a real one
    to show.

    The suggested command deliberately carries NO --until/--from flags: it is
    a CONTINUE command, and the done-markers already make it resume exactly
    where this run stopped -- carrying a --from would pointlessly redo done
    stages. (A slice that explicitly NAMED a post-gate stage never reaches
    this message; it fails upfront via _fw_slice_needs_gamescript_message.)
    """
    return (
        "fw: no gamescript configured. extract/asr/subtitle-bind are done; speaker + "
        "story-order matching needs your own copy of the Forbidden West gamescript -- "
        "BYO, this repo can't ship game text (see docs/BYO.md). Re-run with:\n"
        f"    deciwaves fw run --package {_quoted_package(package)} --gamescript <path-to-gamescript>\n"
        "to continue with match -> full-reel -> render, or persist it once with "
        "`deciwaves setup --fw-gamescript <path-to-gamescript>` so future runs (and "
        "guided mode) don't need the flag at all."
    )


def _fw_slice_needs_gamescript_message(package: str, named_stage: str,
                                       from_stage: str | None, until_stage: str | None) -> str:
    """The upfront failure message when --until/--from explicitly names a
    post-gamescript-gate stage but no gamescript is configured at all: unlike
    the plain-run BYO soft stop (rc 0, message above), this run provably can't
    do what was asked. Same issue-#23 contract: show the exact re-run command,
    including the slice flags the user gave -- a flagless re-run would execute
    MORE of the pipeline than they asked for."""
    slice_flags = ""
    if from_stage:
        slice_flags += f" --from {from_stage}"
    if until_stage:
        slice_flags += f" --until {until_stage}"
    return (
        f"fw: {named_stage} needs a gamescript: speaker + story-order matching past "
        f"subtitle-bind needs your own copy of the Forbidden West gamescript -- BYO, "
        f"this repo can't ship game text (see docs/BYO.md). Re-run with:\n"
        f"    deciwaves fw run --package {_quoted_package(package)}{slice_flags} "
        f"--gamescript <path-to-gamescript>\n"
        f"or persist it once with `deciwaves setup --fw-gamescript <path-to-gamescript>`."
    )

def _fw_extract_argv(ctx: dict) -> list:
    return ["--package", ctx["package"]]


def _fw_asr_argv(ctx: dict) -> list:
    return []


def _fw_subtitle_bind_argv(ctx: dict) -> list:
    # subtitle-bind's own --out default (`subtitle_bind.DEFAULT_OUT`) already
    # matches what match/full-reel/weave read by default, so this stage needs
    # no override -- see test_fw_subtitle_manifest_defaults.py for the lockstep
    # test guarding that (issue #17: they used to disagree, and this function
    # used to paper over it with an explicit --out).
    return ["--package-dir", ctx["package"]]


def _fw_match_argv(ctx: dict) -> list:
    return ["--gamescript", ctx["gamescript"]]


def _fw_full_reel_argv(ctx: dict) -> list:
    return []


def _fw_render_argv(ctx: dict) -> list:
    # render's own --manifest/--tiers defaults (`render.DEFAULT_MANIFEST` /
    # `render.DEFAULT_TIERS`) already match the full-reel stage's output and
    # ship set, so this stage needs no override for them -- see
    # test_fw_render.py's lockstep test (issue #17: they used to diverge).
    return ["--stem", "fw_story_full", "--uniform-mono"]


def _run_fw(cfg: dict, extra_argv: list) -> int:
    # The chain is executed in two `_run_chain` calls (split around the BYO
    # --gamescript gate below), but it is one declared pipeline -- pass the
    # full, ordered stage list as `full_chain` to both calls so marker
    # invalidation (issue #37) sees stages on the far side of the gate too.
    full_chain = [
        Stage("extract", STAGES["fw"]["extract"][0], _fw_extract_argv),
        Stage("asr", STAGES["fw"]["asr"][0], _fw_asr_argv, gpu=True),
        Stage("subtitle-bind", STAGES["fw"]["subtitle-bind"][0], _fw_subtitle_bind_argv),
        Stage("match", STAGES["fw"]["match"][0], _fw_match_argv),
        Stage("full-reel", STAGES["fw"]["full-reel"][0], _fw_full_reel_argv),
        Stage("render", STAGES["fw"]["render"][0], _fw_render_argv),
    ]
    ap = argparse.ArgumentParser(
        prog="deciwaves fw run",
        description="Run the FW pipeline end-to-end: extract -> asr -> subtitle-bind, "
                    "then (with a BYO gamescript) match -> full-reel -> render.",
    )
    ap.add_argument("--package", help="FW package/install path (default: from `deciwaves setup`)")
    ap.add_argument("--gamescript", help="path to your own Forbidden West gamescript transcript "
                                          "(BYO, optional -- required only to run "
                                          "match/full-reel/render; default: from "
                                          "`deciwaves setup --fw-gamescript`)")
    _add_slice_flags(ap, full_chain)
    ns = _parse_or_exit(ap, extra_argv)
    if isinstance(ns, int):
        return ns

    package = ns.package or cfg.get("fw_package")
    if not package:
        return _missing_config("fw", "FW package (fw_package)", "--package")

    # An explicit --gamescript beats a saved fw_gamescript config value; an
    # explicitly-given empty/None flag falls back to the saved config, same
    # `or`-based precedence as package/data_dir/oodle above (issue #23).
    gamescript = ns.gamescript or cfg.get("fw_gamescript", "")

    ctx = {"package": package, "gamescript": gamescript}
    names = [s.name for s in full_chain]
    gate_idx = names.index("match")  # first stage past the BYO --gamescript gate
    last_idx, rc = _slice_bounds("fw", full_chain, ns.from_stage, ns.until)
    if rc:
        return rc

    # The gamescript gate is validated UPFRONT for any run whose slice crosses
    # it -- same reasoning as the upfront GPU gate (issue #33): a run known to
    # be doomed at the gate must fail before extract/asr's hours are spent,
    # not after chunk1. A slice ending BEFORE the gate never consumes the
    # gamescript, so it is deliberately not validated there (`--until
    # subtitle-bind` with a broken configured gamescript still scans fine --
    # config health is doctor's job, see doctor.check_fw_gamescript).
    if last_idx >= gate_idx:
        named_post_gate = next((s for s in (ns.until, ns.from_stage)
                                if s and names.index(s) >= gate_idx), None)
        if not gamescript and named_post_gate is not None:
            # Unlike the plain-run BYO stop below (rc 0: "ran as far as it
            # could"), an explicit --until/--from naming a post-gate stage is
            # a request this run provably can't honor -- fail it before any
            # stage runs, and before --from's marker delete below.
            print(_fw_slice_needs_gamescript_message(package, named_post_gate,
                                                     ns.from_stage, ns.until))
            return 1
        if gamescript and not os.path.isfile(gamescript):
            # Loud and nonzero whether this path came from an explicit
            # --gamescript (issue #38) or from a configured-but-now-missing
            # fw_gamescript (issue #23) -- unlike "never configured", this is
            # "configured and broken", which must fail the run the same way a
            # missing --ds-install/--hzd-package/--fw-package does.
            print(f"deciwaves fw run: gamescript not found: {gamescript} "
                  f"(check --gamescript, or re-run `deciwaves setup --fw-gamescript <path>`)")
            return 1

    if ns.from_stage:
        _remove_marker("fw", ns.from_stage)  # --from's contract: delete, then run normally
    chunk1 = full_chain[:min(last_idx + 1, gate_idx)]
    chunk2 = full_chain[gate_idx:last_idx + 1]

    rc = _run_chain("fw", chunk1, ctx, full_chain=full_chain)
    if rc:
        return rc
    if not chunk2:
        # --until stops inside (or exactly at the end of) the pre-gamescript
        # chunk: the run ended because the user said stop, so the BYO stop
        # message -- which explains how to CONTINUE past subtitle-bind --
        # would misreport why the run ended. Skip the gate entirely.
        return 0
    if not gamescript:
        print(_fw_byo_message(package))
        return 0

    return _run_chain("fw", chunk2, ctx, full_chain=full_chain)  # already --until-sliced


# ---------------------------------------------------------------------------

_RUNNERS = {"ds": _run_ds, "hzd": _run_hzd, "fw": _run_fw}


def run_game(game: str, cfg: dict, extra_argv: list) -> int:
    runner = _RUNNERS.get(game)
    if runner is None:
        print(f"deciwaves: unknown game {game!r}")
        return 2
    return runner(cfg, extra_argv)
