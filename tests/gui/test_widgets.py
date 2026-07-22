"""Reusable onboarding widgets (#112, #265): HelpIcon, Pill, CollapsibleSection,
and GPU-aware AsrInstallHint. Skips without [gui]."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from deciwaves.gui.widgets import (  # noqa: E402
    AsrInstallHint,
    CollapsibleSection,
    HelpIcon,
    Pill,
)


def test_help_icon_carries_text_in_tooltip_and_whatsthis(qtbot):
    icon = HelpIcon("Bring Your Own — you supply your own game files.")
    qtbot.addWidget(icon)
    assert "Bring Your Own" in icon.help_text()
    assert "Bring Your Own" in icon.toolTip()
    assert "Bring Your Own" in icon.whatsThis()


def test_pill_shows_label(qtbot):
    pill = Pill("Optional")
    qtbot.addWidget(pill)
    assert pill.text() == "Optional"


def test_collapsible_hides_body_when_collapsed(qtbot):
    body = QLabel("detail")
    section = CollapsibleSection("Setup", body)
    qtbot.addWidget(section)
    section.show()
    section.set_collapsed(True)
    assert section.is_collapsed() is True
    assert body.isVisibleTo(section) is False
    section.set_collapsed(False)
    assert body.isVisibleTo(section) is True


def test_collapsible_shows_summary_text(qtbot):
    section = CollapsibleSection("Doctor", QLabel("rows"))
    qtbot.addWidget(section)
    section.set_summary("3 checks OK · 2 optional")
    assert "3 checks OK" in section.summary_text()


# --- AsrInstallHint (#265) --------------------------------------------------


def test_asr_install_hint_shows_why_text(qtbot):
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert "whisperx" in hint._why.text().lower()
    assert "GPU acceleration" in hint._why.text()


def test_asr_install_hint_shows_pytorch_link_and_optional_note(qtbot):
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    labels = hint.findChildren(QLabel)
    texts = " ".join(l.text().lower() for l in labels)
    assert "pytorch.org" in texts
    assert "optional — the pipeline runs without it" in texts


def test_asr_install_hint_command_is_selectable(qtbot):
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert hint._cmd_label.textInteractionFlags() & Qt.TextSelectableByMouse
    assert hint._cmd_label.textInteractionFlags() & Qt.TextSelectableByKeyboard


def test_asr_install_hint_copy_button_exists(qtbot):
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert hint._copy_btn.toolTip(), "Copy button should have a non-empty tooltip"


def test_asr_install_hint_command_text_needs_probe(monkeypatch, qtbot):
    from deciwaves.gui.gpu_probe import CPU_RESULT
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe.probe_gpu",
        lambda: CPU_RESULT)
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert hint.command_text() != ""
    assert "pip install" in hint.command_text()
    assert "[asr]" in hint.command_text()


def test_asr_install_hint_starts_hidden(qtbot):
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert not hint.isVisible()


def test_asr_install_hint_probes_only_once_on_show(qtbot, monkeypatch):
    from deciwaves.gui.gpu_probe import CPU_RESULT
    calls = []
    monkeypatch.setattr(
        "deciwaves.gui.gpu_probe.probe_gpu",
        lambda: (calls.append(1), CPU_RESULT)[-1])
    hint = AsrInstallHint()
    qtbot.addWidget(hint)
    assert not hint._probed
    hint.show()
    assert hint._probed
    hint.hide()
    hint.show()
    assert len(calls) == 1
    assert hint.command_text() != ""
