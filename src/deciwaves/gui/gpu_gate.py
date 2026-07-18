"""The blocking pre-bind CUDA dialog (#68, spec §3).

Thin Qt wrapper over :func:`~deciwaves.gui.cuda_probe.needs_gpu_warning`: proceed silently
when a GPU is visible (or the game has no GPU stage), otherwise make the user confirm the
days-on-CPU risk the CLI's import-only gate never catches. #69 calls this before Bind."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from deciwaves.gui.cuda_probe import GPU_WARNING_TEXT, needs_gpu_warning


def confirm_gpu(parent: QWidget | None, game: str, payload: dict | None) -> bool:
    """Return True to proceed with the GPU stage, False to abort."""
    if not needs_gpu_warning(game, payload):
        return True
    resp = QMessageBox.warning(parent, "GPU check", GPU_WARNING_TEXT,
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return resp == QMessageBox.Yes
