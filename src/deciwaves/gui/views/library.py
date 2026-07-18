"""Library view (issue #67): the line list, filters, selection, inline preview and
export land across #70-#72. The skeleton ships a placeholder so the two-view shell is
complete and navigable."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LibraryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        placeholder = QLabel("Library — line list, filters, preview, export (coming: #70–#72).")
        placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(placeholder)
