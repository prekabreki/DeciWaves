"""confirm_gpu: the blocking pre-bind CUDA dialog (#68, spec §3). The decision logic is
tested Qt-free in test_cuda_probe; here we cover the thin Qt wrapper -- that it skips the
dialog entirely when a GPU is present, and maps the modal's Yes/No to proceed/abort.
Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from deciwaves.gui.gpu_gate import confirm_gpu  # noqa: E402


def _cuda(status):
    return {"ok": True, "checks": [{"name": "cuda", "ok": True, "status": status,
                                    "message": "", "fix": ""}]}


def test_proceeds_without_a_dialog_when_gpu_is_available(qtbot, monkeypatch):
    # if a dialog ever pops here the test would hang, so make it explode instead
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: pytest.fail("dialog shown when GPU available"))
    assert confirm_gpu(None, "hzd", _cuda("ok")) is True


def test_ds_never_prompts(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: pytest.fail("dialog shown for DS"))
    assert confirm_gpu(None, "ds", None) is True


def test_maps_yes_to_proceed_and_no_to_abort(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    assert confirm_gpu(None, "hzd", None) is True
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    assert confirm_gpu(None, "fw", _cuda("unavailable")) is False
