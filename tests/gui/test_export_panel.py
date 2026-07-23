"""Export panel widget tests: round-trip order UI (Task 5 of CSV order round-trip)."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QFileDialog  # noqa: E402

from deciwaves.gui.export import ExportPanel  # noqa: E402


@pytest.fixture
def panel(qtbot):
    p = ExportPanel()
    qtbot.addWidget(p)
    return p


def test_round_trip_enable_and_status(panel):
    panel.set_context("ds", ".", checked_count=3, can_mp3=True, can_catalog=True,
                      order_active=False, order_count=0)
    assert panel.export_order_enabled() is True
    assert panel.import_enabled() is True
    assert panel.revert_enabled() is False
    assert "automatic" in panel.order_status_text().lower()
    panel.set_context("ds", ".", checked_count=3, can_mp3=True, can_catalog=True,
                      order_active=True, order_count=42)
    assert panel.revert_enabled() is True
    assert "42" in panel.order_status_text()


def test_round_trip_signals(panel, qtbot, tmp_path, monkeypatch):
    panel.set_context("ds", str(tmp_path), 3, True, True, order_active=True, order_count=1)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "e.csv"), "")))
    with qtbot.waitSignal(panel.import_order_requested):
        panel._on_import_clicked()
    with qtbot.waitSignal(panel.revert_order_requested):
        panel._order_revert_btn.click()


def test_instructions_present(panel):
    assert panel._instructions.text()
