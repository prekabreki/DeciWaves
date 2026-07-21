"""Shared child-process environment setup for GUI subprocess runners.

Provides :func:`utf8_environment`, a :class:`~PySide6.QtCore.QProcessEnvironment`
with UTF-8 and unbuffered mode forced so child output renders correctly in the
live console (mojibake class from #59)."""
from __future__ import annotations

from PySide6.QtCore import QProcessEnvironment


def utf8_environment() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")
    return env
