"""Shared child-process environment for the GUI's QProcess runners (#118).

Both runners -- :class:`~deciwaves.gui.jobs.JobRunner` (the live pipeline console) and
:class:`~deciwaves.gui.capture.CaptureRunner` (setup/doctor) -- decode the child's stdout
as UTF-8, so both must force the child into UTF-8 *and* unbuffered I/O. Without it a Python
child writing to a pipe on Windows uses the ANSI code page (mojibake in a displayed
non-ASCII path; issue #59's console em-dash) and buffers its stdout, so the hours-long
pipeline console would stall until a flush instead of streaming line-by-line."""
from __future__ import annotations

from PySide6.QtCore import QProcessEnvironment


def utf8_environment() -> QProcessEnvironment:
    """A copy of the system environment forcing the child to UTF-8, unbuffered stdio."""
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")  # stream line-by-line, don't block-buffer the pipe
    return env
