"""Qt-free stage-strip model + Scan/Bind/Re-run argv builders (#69, spec §5.1/§5.2).

The chain comes straight from ``run.run_chain`` -- the same list ``deciwaves <game> run``
executes -- so the strip can't render a phantom stage or drift from the tokens
``--until``/``--from`` accept. Marker state is read from ``out/<game>/.done-<stage>``; the
GUI never writes or deletes markers (the CLI owns them), so every control here is an argv
the shell's JobRunner runs."""
from __future__ import annotations

import os
from dataclasses import dataclass

from deciwaves.cli.run import run_chain
from deciwaves.gui.cli_command import build_cli_command


@dataclass(frozen=True)
class StageState:
    name: str
    gpu: bool
    done: bool


def _marker_path(workspace: str, game: str, stage: str) -> str:
    return os.path.join(workspace, "out", game, f".done-{stage}")


def stage_states(game: str, workspace: str) -> list[StageState]:
    return [StageState(s.name, s.gpu, os.path.isfile(_marker_path(workspace, game, s.name)))
            for s in run_chain(game)]


def has_gpu_stage(game: str) -> bool:
    return any(s.gpu for s in run_chain(game))


def scan_target(game: str) -> str:
    """The last stage before the first GPU stage -- the Scan button's ``--until`` target.
    Games with no GPU stage (DS) scan the whole chain (its last stage)."""
    chain = run_chain(game)
    for i, s in enumerate(chain):
        if s.gpu:
            return chain[i - 1].name if i > 0 else s.name
    return chain[-1].name


def rerun_hits_gpu(game: str, stage: str) -> bool:
    """True if re-running ``from stage`` would reach a GPU stage (so the shell warns).
    False for an unknown stage."""
    chain = run_chain(game)
    names = [s.name for s in chain]
    if stage not in names:
        return False
    return any(s.gpu for s in chain[names.index(stage):])


def scan_argv(base: list[str], workspace: str, game: str) -> list[str]:
    """Scan = run the cheap, no-GPU stages: ``run --until <last pre-GPU stage>``."""
    return build_cli_command(base, workspace, game, "run", "--until", scan_target(game))


def process_argv(base: list[str], workspace: str, game: str) -> list[str]:
    """Bind/Process = ``run`` onward; markers make it resume from the first incomplete
    (GPU) stage, and bind falls back to its own bounded --sample-cap default."""
    return build_cli_command(base, workspace, game, "run")


def rerun_from_argv(base: list[str], workspace: str, game: str, stage: str) -> list[str]:
    """"Re-run from here" = ``run --from <stage>``; the CLI deletes that marker and cascade-
    invalidates later ones. The GUI never deletes markers itself."""
    return build_cli_command(base, workspace, game, "run", "--from", stage)


def escalate_bind_argv(base: list[str], workspace: str, game: str = "hzd") -> list[str]:
    """"Transcribe all" = ``run --from bind --sample-cap 0`` -- --from drops .done-bind
    (inert --sample-cap changes otherwise) and re-runs bind uncapped (spec §5.4)."""
    return build_cli_command(base, workspace, game, "run", "--from", "bind", "--sample-cap", "0")
