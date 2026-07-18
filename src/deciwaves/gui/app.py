"""QApplication bootstrap (issue #67). Kept separate from ``gui/__init__`` so importing
the package never constructs Qt objects -- ``launch()`` imports this lazily."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from deciwaves.gui.shell import MainWindow


def run_app(argv=None) -> int:
    # The GUI doesn't parse CLI tokens itself; hand Qt just the program name so it
    # can't misread a stray token as a Qt option.
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.show()
    return app.exec()
