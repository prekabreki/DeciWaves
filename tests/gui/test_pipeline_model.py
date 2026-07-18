"""Qt-free stage-strip model + Scan/Bind/Re-run argv builders (#69, spec §5.1/§5.2). No
importorskip: the chain comes from `run.run_chain` (single source of truth) and markers are
plain files, so the strip's contract is covered on a base install."""
import os

from deciwaves.gui.pipeline_model import (
    escalate_bind_argv,
    has_gpu_stage,
    process_argv,
    rerun_from_argv,
    rerun_hits_gpu,
    scan_argv,
    scan_target,
    stage_states,
)

BASE = ["py", "-m", "deciwaves.cli.main"]


def _touch_marker(ws, game, stage):
    d = os.path.join(ws, "out", game)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f".done-{stage}"), "w").close()


def test_stage_states_ds_chain_all_pending(tmp_path):
    states = stage_states("ds", str(tmp_path))
    assert [s.name for s in states] == ["catalog", "order", "render"]
    assert all(not s.done for s in states)
    assert all(not s.gpu for s in states)


def test_stage_states_reflect_markers_and_gpu_flag(tmp_path):
    _touch_marker(str(tmp_path), "hzd", "catalog")
    _touch_marker(str(tmp_path), "hzd", "clip-index")
    states = {s.name: s for s in stage_states("hzd", str(tmp_path))}
    assert states["catalog"].done and states["clip-index"].done
    assert not states["wem-metadata"].done and not states["bind"].done
    assert states["bind"].gpu is True and states["catalog"].gpu is False


def test_scan_target_is_last_pre_gpu_stage():
    assert scan_target("ds") == "render"          # no GPU stage -> whole chain
    assert scan_target("hzd") == "wem-metadata"   # the stage before bind
    assert scan_target("fw") == "extract"         # the stage before asr


def test_has_gpu_stage():
    assert has_gpu_stage("ds") is False
    assert has_gpu_stage("hzd") is True
    assert has_gpu_stage("fw") is True


def test_scan_argv_uses_until_and_workspace_before_game(tmp_path):
    argv = scan_argv(BASE, str(tmp_path), "hzd")
    assert argv[-3:] == ["run", "--until", "wem-metadata"]
    assert argv.index("--workspace") < argv.index("hzd")


def test_process_argv_is_plain_run(tmp_path):
    argv = process_argv(BASE, str(tmp_path), "hzd")
    assert argv[-1] == "run"
    assert "--until" not in argv


def test_rerun_from_argv(tmp_path):
    argv = rerun_from_argv(BASE, str(tmp_path), "ds", "order")
    assert argv[-2:] == ["--from", "order"]


def test_rerun_hits_gpu_when_from_stage_reaches_a_gpu_stage():
    # re-running from a pre-GPU stage cascades into the GPU stage -> the shell must warn
    assert rerun_hits_gpu("hzd", "catalog") is True     # ...->bind
    assert rerun_hits_gpu("hzd", "render") is False     # after bind, no GPU left
    assert rerun_hits_gpu("hzd", "bind") is True
    assert rerun_hits_gpu("fw", "extract") is True      # ...->asr
    assert rerun_hits_gpu("fw", "match") is False       # after asr
    assert rerun_hits_gpu("ds", "catalog") is False     # DS has no GPU stage
    assert rerun_hits_gpu("hzd", "nonexistent") is False


def test_escalate_bind_argv_uncaps_via_from_bind(tmp_path):
    # --from bind deletes .done-bind (CLI's job) and re-runs uncapped -- the GUI never
    # touches markers itself (spec §5.2/§5.4).
    argv = escalate_bind_argv(BASE, str(tmp_path))
    assert argv[argv.index("--from") + 1] == "bind"
    assert argv[argv.index("--sample-cap") + 1] == "0"
