"""Small reusable onboarding widgets (#112), shared across Setup/Doctor/coverage/
issues/game-panel so the look and behaviour are defined and tested once.

- :class:`HelpIcon` -- a muted ⓘ label carrying a rich tooltip + whats-this, for
  expanding jargon at its point of use.
- :class:`Pill` -- a small "Optional"/"Needed" badge that makes the per-game
  optional-vs-required framing unmissable.
- :class:`CollapsibleSection` -- a header (▾/▸ toggle + summary) over a body that
  hides on collapse, for the first-run declutter of the long Setup/Doctor panels.
- :class:`AsrInstallHint` -- a GPU-aware ASR install instruction widget: what/why,
  generated command (selectable), Copy button, PyTorch doc link, and an explicit
  "optional" note (#265)."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from deciwaves.gui.theme import NEUTRAL, WARN


class HelpIcon(QLabel):
    """A muted ⓘ that shows *text* on hover (tooltip) and via What's-This."""

    def __init__(self, text: str, parent=None):
        super().__init__("ⓘ", parent)
        self.setToolTip(text)
        self.setWhatsThis(text)
        self.setStyleSheet(f"color: {NEUTRAL};")
        self.setCursor(Qt.WhatsThisCursor)

    def help_text(self) -> str:
        return self.toolTip()


_PILL_TONES = {"optional": NEUTRAL, "needed": WARN}


class Pill(QLabel):
    """A small rounded badge; *tone* picks the colour (``optional``/``needed``)."""

    def __init__(self, label: str, tone: str = "optional", parent=None):
        super().__init__(label, parent)
        colour = _PILL_TONES.get(tone, NEUTRAL)
        self.setStyleSheet(
            f"color: white; background: {colour}; "
            "border-radius: 6px; padding: 0px 6px;")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)


class CollapsibleSection(QWidget):
    """A ▾/▸ header (title + optional one-line summary) over a *body* that hides
    when collapsed. Used to declutter the long Setup/Doctor panels on first run:
    a healthy returning user sees a compact summary; a broken/first-run user sees
    the section expanded where the problem is (#112)."""

    def __init__(self, title: str, body: QWidget, parent=None):
        super().__init__(parent)
        self._body = body
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setStyleSheet("border: none;")
        self._title = title
        self._summary = QLabel("")
        self._summary.setStyleSheet(f"color: {NEUTRAL};")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._toggle)
        header.addWidget(self._summary, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(header)
        outer.addWidget(self._body)

        self._toggle.toggled.connect(self._on_toggled)
        self._render_header(expanded=True)

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._render_header(expanded)

    def _render_header(self, expanded: bool) -> None:
        arrow = "▾" if expanded else "▸"
        self._toggle.setText(f"{arrow} {self._title}")

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def summary_text(self) -> str:
        return self._summary.text()

    def set_collapsed(self, collapsed: bool) -> None:
        self._toggle.setChecked(not collapsed)

    def is_collapsed(self) -> bool:
        return not self._toggle.isChecked()

    def expand(self) -> None:
        self._toggle.setChecked(True)


_HIGHLIGHT_COLOUR = "#1b6ec2"
_HIGHLIGHT_DURATION_MS = 800


def flash_highlight(widget: QWidget) -> None:
    widget.setStyleSheet(f"border: 2px solid {_HIGHLIGHT_COLOUR};")
    QTimer.singleShot(_HIGHLIGHT_DURATION_MS, lambda: widget.setStyleSheet(""))


class AsrInstallHint(QWidget):
    """GPU-aware ASR install instruction widget (#265).

    Renders: what's needed + why, the GPU-aware install **steps** (each a
    selectable command with its own Copy button), the PyTorch doc link, an
    explicit "optional" note, and a "re-check" button the shell wires to a fresh
    Doctor run so the status updates after the user installs.

    With a GPU there are two steps (CUDA PyTorch, then ``deciwaves[asr]``) because
    ``--index-url`` replaces PyPI and the pytorch index has no whisperx — see
    :func:`deciwaves.gui.gpu_probe.build_asr_install_steps`.

    Probes the GPU lazily on first show, then caches the result — no pip execution
    or terminal launch (that's deferred to #77).
    """

    recheck_requested = Signal()  # user clicked "re-check" after installing

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probed = False
        self._steps: list[tuple[str, str]] = []
        self._cmd_labels: list[QLabel] = []
        self._copy_btns: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._why = QLabel(
            "Speech recognition (ASR, powered by whisperx) attaches subtitles "
            "and speakers to the audio during the Bind step for Horizon Zero "
            "Dawn and Forbidden West. You can scan and preview lines without "
            "it — you need it to produce finished HZD / Forbidden West reels. "
            "It runs many times faster on an NVIDIA GPU; on CPU the Bind step "
            "can take days. Install with:")
        self._why.setWordWrap(True)
        self._why.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self._why)

        # Steps (label + command + Copy) are populated on first show by _probe().
        self._steps_container = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._steps_container)

        self._pytorch_link = QLabel(
            '<a href="https://pytorch.org/get-started/locally/">'
            'https://pytorch.org/get-started/locally/</a>')
        self._pytorch_link.setOpenExternalLinks(True)
        self._pytorch_link.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            | Qt.LinksAccessibleByMouse)
        layout.addWidget(self._pytorch_link)

        self._optional_note = QLabel(
            "Optional for browsing & preview · needed to finish HZD and "
            "Forbidden West.")
        self._optional_note.setStyleSheet(
            f"color: {NEUTRAL}; font-style: italic;")
        self._optional_note.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self._optional_note)

        recheck_row = QHBoxLayout()
        self._recheck_btn = QPushButton("I've installed it — re-check")
        self._recheck_btn.setToolTip(
            "Re-run Doctor to detect the newly installed GPU / ASR support")
        self._recheck_btn.clicked.connect(self.recheck_requested)
        recheck_row.addWidget(self._recheck_btn)
        recheck_row.addStretch(1)
        layout.addLayout(recheck_row)

    def _probe(self) -> None:
        if self._probed:
            return
        self._probed = True
        from deciwaves.gui.gpu_probe import build_asr_install_steps, probe_gpu
        self._steps = build_asr_install_steps(probe_gpu())
        for label, command in self._steps:
            step_label = QLabel(label)
            step_label.setWordWrap(True)
            step_label.setStyleSheet("font-weight: bold;")
            self._steps_layout.addWidget(step_label)

            row = QHBoxLayout()
            cmd_label = QLabel(command)
            cmd_label.setWordWrap(True)
            cmd_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            row.addWidget(cmd_label, 1)
            self._cmd_labels.append(cmd_label)

            copy_btn = QPushButton("Copy")
            copy_btn.setToolTip("Copy this command to the clipboard")
            copy_btn.clicked.connect(
                lambda _checked=False, cmd=command: self._copy(cmd))
            row.addWidget(copy_btn)
            self._copy_btns.append(copy_btn)
            self._steps_layout.addLayout(row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._probe()

    def _copy(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def commands(self) -> list[str]:
        """The ordered install command(s); probes on first access."""
        self._probe()
        return [cmd for _label, cmd in self._steps]
