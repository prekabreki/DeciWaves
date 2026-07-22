"""Qt-free pre-bind CUDA probe (#68, spec §3). No importorskip -- pure decision logic.

The CLI's GPU gate only checks that `whisperx` imports, so CPU-only torch sails through
and then grinds for days. The GUI adds this probe before an HZD/FW bind."""
from deciwaves.gui.cuda_probe import (
    GPU_WARNING_TEXT,
    cuda_display_text,
    cuda_message,
    cuda_status,
    needs_gpu_warning,
)


def _payload(cuda_status_value, message=""):
    return {"ok": True, "checks": [{"name": "cuda", "ok": True,
                                    "status": cuda_status_value, "message": message, "fix": ""}]}


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


# --- cuda_message accessor ---------------------------------------------------

def test_cuda_message_reads_the_message_field():
    assert cuda_message(_payload("unavailable", "CUDA: torch not installed")) == "CUDA: torch not installed"
    assert cuda_message(_payload("unavailable", "CUDA: torch installed but no GPU visible")) == "CUDA: torch installed but no GPU visible"


def test_cuda_message_missing_check_is_empty():
    assert cuda_message({"ok": True, "checks": []}) == ""
    assert cuda_message({}) == ""


# --- cuda_display_text: distinguishes all four doctor cuda outcomes ----------

def test_display_text_cuda_ready():
    assert cuda_display_text(_payload("ok", "CUDA: available (NVIDIA GeForce RTX 4080)")) == "GPU: CUDA ready"


def test_display_text_unknown_no_doctor_run():
    assert cuda_display_text(None) == "GPU: unknown — run Doctor to check CUDA"
    assert cuda_display_text({}) == "GPU: unknown — run Doctor to check CUDA"


def test_display_text_torch_not_installed():
    payload = _payload("unavailable", "CUDA: torch not installed (informational; see ASR extra)")
    assert "acceleration not installed" in cuda_display_text(payload)
    assert "see ASR extra" in cuda_display_text(payload)


def test_display_text_no_gpu_visible():
    payload = _payload("unavailable", "CUDA: torch installed but no GPU visible (informational)")
    assert cuda_display_text(payload) == "GPU: no CUDA GPU visible"


def test_display_text_torch_import_failed():
    payload = _payload("unavailable", "CUDA: torch import failed (DLL load failed) (informational)")
    assert cuda_display_text(payload) == "GPU: torch import failed"


def test_display_text_torch_not_installed_does_not_say_no_gpu():
    payload = _payload("unavailable", "CUDA: torch not installed (informational; see ASR extra)")
    text = cuda_display_text(payload)
    assert "no CUDA GPU" not in text
    assert "acceleration not installed" in text


def test_display_text_no_gpu_does_not_say_not_installed():
    payload = _payload("unavailable", "CUDA: torch installed but no GPU visible (informational)")
    text = cuda_display_text(payload)
    assert "not installed" not in text
    assert "no CUDA GPU visible" in text
