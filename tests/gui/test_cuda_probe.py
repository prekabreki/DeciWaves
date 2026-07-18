"""Qt-free pre-bind CUDA probe (#68, spec §3). No importorskip -- pure decision logic.

The CLI's GPU gate only checks that `whisperx` imports, so CPU-only torch sails through
and then grinds for days. The GUI adds this probe before an HZD/FW bind."""
from deciwaves.gui.cuda_probe import GPU_WARNING_TEXT, cuda_status, needs_gpu_warning


def _payload(cuda_status_value):
    return {"ok": True, "checks": [{"name": "cuda", "ok": True,
                                    "status": cuda_status_value, "message": "", "fix": ""}]}


def test_cuda_status_reads_the_cuda_check():
    assert cuda_status(_payload("ok")) == "ok"
    assert cuda_status(_payload("unavailable")) == "unavailable"


def test_cuda_status_missing_check_is_empty():
    assert cuda_status({"ok": True, "checks": []}) == ""
    assert cuda_status({}) == ""


def test_warn_before_hzd_or_fw_bind_when_no_gpu():
    assert needs_gpu_warning("hzd", _payload("unavailable")) is True
    assert needs_gpu_warning("fw", _payload("unavailable")) is True


def test_no_warning_when_cuda_available():
    assert needs_gpu_warning("hzd", _payload("ok")) is False
    assert needs_gpu_warning("fw", _payload("ok")) is False


def test_ds_never_warns_it_has_no_gpu_stage_in_the_default_chain():
    assert needs_gpu_warning("ds", _payload("unavailable")) is False


def test_missing_payload_warns_for_gpu_games_conservatively():
    # no doctor evidence of a GPU -> warn rather than silently grind for days
    assert needs_gpu_warning("hzd", None) is True
    assert needs_gpu_warning("hzd", {}) is True
    assert needs_gpu_warning("ds", None) is False


def test_warning_text_matches_the_spec_wording():
    assert GPU_WARNING_TEXT == "No GPU visible — this stage may take days on CPU. Continue?"
