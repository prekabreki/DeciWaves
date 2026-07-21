"""Regression tests for the autouse QSettings-isolation fixture (issue #199).

Verifies that default-constructed ``QSettings("DeciWaves", "gui")`` resolves
to a file-backed .ini under the per-test temp dir, not the real registry.
"""
import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings

from deciwaves.gui.shell import MainWindow


def test_qsettings_isolation_prevents_registry_access(qtbot, tmp_path):
    """Construct MainWindow(), close it, and verify settings land under tmp_path."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.close()

    fn = os.path.normpath(QSettings("DeciWaves", "gui").fileName())
    assert os.path.normpath(str(tmp_path)) in fn
    assert fn.endswith(".ini")


def test_qsettings_folder_contains_settings_after_close(qtbot, tmp_path):
    """After constructing and closing MainWindow, the .ini file exists on disk."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.close()
    w._settings.sync()

    ini_files = list(tmp_path.glob("*.ini"))
    assert len(ini_files) >= 1
