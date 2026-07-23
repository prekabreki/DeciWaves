"""Qt-free journey computation for the onboarding guide rail (#112). No importorskip:
the rail's ordering/completion contract is covered on a base install so it can't drift
under a no-[gui] CI run."""
from deciwaves.cli.doctor import Availability
from deciwaves.gui.guide_model import (
    ActionTarget,
    StepId,
    build_journey,
    export_done,
    tools_ready,
)


def _payload(*names_ok):
    """A doctor payload where each name in *names_ok* is an OK check."""
    return {"ok": True, "checks": [
        {"name": n, "ok": True, "status": "ok", "message": "", "fix": ""}
        for n in names_ok]}


_ALL_TOOLS = ("vgmstream-cli", "VGAudioCli", "ffmpeg")


def _journey(**kw):
    base = dict(doctor_payload=None, game="ds", game_label="Death Stranding",
                game_status=Availability.OK, workspace="")
    base.update(kw)
    return build_journey(**base)


def test_tools_ready_true_only_when_all_three_present():
    assert tools_ready(_payload(*_ALL_TOOLS)) is True
    assert tools_ready(_payload("vgmstream", "VGAudio")) is False
    assert tools_ready(None) is False


def test_tools_ready_matches_doctor_display_names():
    payload = _payload("vgmstream-cli", "VGAudioCli", "ffmpeg")
    assert tools_ready(payload) is True
    assert tools_ready(_payload("vgmstream", "VGAudio")) is False


def test_not_owned_game_yields_neutral_line_no_steps():
    j = _journey(game_status=Availability.NOT_CONFIGURED)
    assert j.game_owned is False
    assert j.steps == ()
    assert j.next_action is None
    assert "Death Stranding" in j.next_hint


def test_first_step_is_setup_when_nothing_ready():
    j = _journey()
    assert j.next_action is ActionTarget.SETUP
    setup = next(s for s in j.steps if s.id is StepId.SETUP)
    assert setup.current is True and setup.done is False


def test_workspace_is_live_step_once_tools_ready_but_workspace_blank():
    j = _journey(doctor_payload=_payload(*_ALL_TOOLS), workspace="")
    assert j.next_action is ActionTarget.WORKSPACE


def test_scan_is_live_step_once_setup_and_workspace_done(tmp_path):
    """A GPU game (HZD) shows Scan as the next step."""
    j = _journey(game="hzd", doctor_payload=_payload(*_ALL_TOOLS),
                  workspace=str(tmp_path))
    assert j.next_action is ActionTarget.SCAN
    assert "catalog" in j.next_hint.lower()


def test_gpu_less_game_shows_build_not_scan_bind():
    """DS (no GPU stage) collapses Scan+Bind into a single Build step."""
    j = _journey()
    ids = [s.id for s in j.steps]
    assert StepId.SCAN not in ids
    assert StepId.BIND not in ids
    assert StepId.BUILD in ids


def test_gpu_game_keeps_scan_and_bind():
    j = _journey(game="hzd")
    ids = [s.id for s in j.steps]
    assert StepId.SCAN in ids
    assert StepId.BIND in ids
    assert StepId.BUILD not in ids


def test_running_step_is_propagated_to_step():
    j = _journey(running_step_id=StepId.BUILD)
    build = next(s for s in j.steps if s.id == StepId.BUILD)
    assert build.running


def test_running_step_not_set_when_omitted():
    j = _journey()
    assert all(not s.running for s in j.steps)


def test_hint_shows_in_progress_when_running():
    j = _journey(running_step_id=StepId.SETUP)
    assert "In progress:" in j.next_hint


def test_hint_shows_next_when_not_running():
    j = _journey()
    assert j.next_hint.startswith("Next:")


def test_export_done_detects_mp3_in_game_output_dir(tmp_path):
    ds_audio = tmp_path / "out" / "audio"
    ds_audio.mkdir(parents=True)
    (ds_audio / "reel_01.mp3").write_bytes(b"x")
    assert export_done(str(tmp_path), "ds") is True
    assert export_done(str(tmp_path), "hzd") is False


def test_export_done_detects_mp3_for_hzd(tmp_path):
    hzd_audio = tmp_path / "out" / "hzd" / "audio"
    hzd_audio.mkdir(parents=True)
    (hzd_audio / "reel_01.mp3").write_bytes(b"x")
    assert export_done(str(tmp_path), "hzd") is True
    assert export_done(str(tmp_path), "ds") is False
