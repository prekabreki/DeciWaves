"""Regression tests for the autouse modal-guard fixture (issue #180). Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget


class _DialogWidget(QWidget):
    """A minimal QWidget whose closeEvent shows a QMessageBox.question dialog."""

    def closeEvent(self, event):
        QMessageBox.question(self, "Confirm quit", "Quit?")
        event.accept()


@pytest.mark.allow_dialogs
def test_close_event_does_not_hang_with_allowed_marker(qtbot):
    """A closeEvent dialog completes without hanging under allow_dialogs."""
    w = _DialogWidget()
    qtbot.addWidget(w)
    w.close()


def test_unexpected_modal_triggers_pytest_fail():
    """Without allow_dialogs, calling QMessageBox.question fails the test."""
    # Direct call to a patched static convenience method.
    with pytest.raises(pytest.fail.Exception) as exc:
        QMessageBox.question(None, "title", "msg")
    assert "QMessageBox.question" in str(exc.value)


def test_unexpected_dialog_exec_fails():
    """Without allow_dialogs, calling QDialog.exec() fails the test."""
    d = QDialog()
    with pytest.raises(pytest.fail.Exception) as exc:
        d.exec()
    assert "QDialog.exec" in str(exc.value)


@pytest.mark.allow_dialogs
def test_allowed_dialog_returns_yes():
    """Under allow_dialogs, QMessageBox.question returns QMessageBox.Yes."""
    ans = QMessageBox.question(None, "title", "msg")
    assert ans == QMessageBox.Yes


@pytest.mark.allow_dialogs
def test_allowed_dialog_exec_returns_value():
    """Under allow_dialogs, QMessageBox.exec returns QMessageBox.Yes."""
    mb = QMessageBox(QMessageBox.Question, "title", "msg")
    assert mb.exec() == QMessageBox.Yes


@pytest.mark.allow_dialogs
def test_allowed_dialog_exec_legacy_alias_returns_value():
    """Under allow_dialogs, QMessageBox.exec_ returns QMessageBox.Yes."""
    mb = QMessageBox(QMessageBox.Question, "title", "msg")
    assert mb.exec_() == QMessageBox.Yes


@pytest.mark.allow_dialogs
def test_allowed_qdialog_exec_returns_value():
    """Under allow_dialogs, QDialog.exec returns QMessageBox.Yes."""
    d = QDialog()
    assert d.exec() == QMessageBox.Yes


@pytest.mark.allow_dialogs
def test_all_close_event_reaches_end(qtbot):
    """Under allow_dialogs, a widget whose closeEvent shows a QMessageBox does not hang."""
    w = _DialogWidget()
    qtbot.addWidget(w)
    w.close()
