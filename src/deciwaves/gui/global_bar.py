"""Global bar shown on both views (issue #67, spec §2): game dropdown, install-status
line, workspace picker, and the single job chip. Visible everywhere because the running
job may belong to a game other than the one currently selected."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
)

# (key, menu label) -- keys match the CLI game tokens / doctor check map.
_GAMES = [("ds", "Death Stranding"),
          ("hzd", "Horizon Zero Dawn"),
          ("fw", "Horizon Forbidden West")]


class GlobalBar(QWidget):
    game_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._combo = QComboBox()
        for key, label in _GAMES:
            self._combo.addItem(label, key)
        self._status = QLabel("")
        self._workspace = QLineEdit()
        self._browse = QPushButton("Browse…")
        self._chip = QLabel("idle")

        layout = QHBoxLayout(self)
        layout.addWidget(QLabel("Game:"))
        layout.addWidget(self._combo)
        layout.addWidget(self._status, 1)
        layout.addWidget(QLabel("Workspace:"))
        layout.addWidget(self._workspace)
        layout.addWidget(self._browse)
        layout.addWidget(self._chip)

        self._combo.currentIndexChanged.connect(
            lambda _i: self.game_changed.emit(self.current_game()))
        self._browse.clicked.connect(self._pick_workspace)

    def current_game(self) -> str:
        return self._combo.currentData()

    def select_game(self, key: str) -> None:
        i = self._combo.findData(key)
        if i >= 0:
            self._combo.setCurrentIndex(i)   # fires currentIndexChanged -> game_changed

    def workspace(self) -> str:
        return self._workspace.text()

    def set_workspace(self, path: str) -> None:
        self._workspace.setText(path)

    def set_install_status(self, text: str, ok: bool) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #167f3b;" if ok else "color: #b00020;")

    def set_job_chip(self, text: str) -> None:
        self._chip.setText(text)

    def _pick_workspace(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose workspace", self._workspace.text() or ".")
        if chosen:
            self._workspace.setText(chosen)
