"""Autouse fixture guarding GUI tests against modal-dialog hangs (issue #180).

Without this fixture, a ``QMessageBox.question`` (or ``.warning``/``.critical``/
``.information``, or any ``QDialog.exec`` / ``QMessageBox.exec``) that fires during
test code or teardown blocks forever in headless CI — no one is at the keyboard.

The fixture monkeypatches all of these to call ``pytest.fail()`` by default, so an
unexpected modal fails the test with a clear message. Tests that intentionally
exercise a dialog can apply ``@pytest.mark.allow_dialogs`` to make the patched
methods return ``QMessageBox.Yes`` instead.

NOTE: This conftest shadows ``tests/conftest.py`` in pytest's prepend import mode,
so all symbols from the parent conftest are re-exported here to keep ``from
conftest import ...`` working in every test file.
"""
from __future__ import annotations

import os as _os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QMessageBox

# ── re-export from tests/conftest.py ────────────────────────────────────────
# Pytest's prepend import mode makes ``from conftest import ...`` resolve to
# THIS file first no matter which directory the test lives in, so the parent
# module's symbols must be present here too or imports like
# ``from conftest import HZD_PACKAGE`` break in non-GUI test files.
_parent_conftest = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "conftest.py")
_parent_ns: dict = {"__file__": _parent_conftest, "__builtins__": __builtins__}
exec(compile(open(_parent_conftest, encoding="utf-8").read(), _parent_conftest, "exec"), _parent_ns)
for _key in list(_parent_ns):
    if not _key.startswith("_"):
        globals()[_key] = _parent_ns[_key]
del _parent_conftest, _parent_ns, _key


def _make_guard(name: str):
    """Return a callable that fails the test when an unexpected modal is shown."""
    def _raiser(*args, **kwargs):
        pytest.fail(
            f"Unexpected modal dialog: {name} was called. "
            "Use @pytest.mark.allow_dialogs to permit dialogs in this test."
        )
    _raiser.__name__ = str(name)
    return _raiser


def _make_allow(name: str):
    """Return a callable that returns ``QMessageBox.Yes`` for an allowed dialog."""
    def _handler(*args, **kwargs):
        return QMessageBox.Yes
    _handler.__name__ = str(name)
    return _handler


@pytest.fixture(autouse=True, scope="function")
def _guard_modals(monkeypatch, request):
    """Monkeypatch all modal-dialog entry points so they cannot hang the suite.

    In guard mode (the default, no ``@pytest.mark.allow_dialogs``), any call to
    a patched method raises ``pytest.fail()`` with the dialog name.

    In allow mode (``@pytest.mark.allow_dialogs``), the patched methods return
    ``QMessageBox.Yes`` so the test can exercise dialog-triggering code without
    hanging. Tests that need a specific return value should monkeypatch the
    individual method themselves (which overrides this fixture's patch).
    """
    allow = request.node.get_closest_marker("allow_dialogs")
    make = _make_allow if allow is not None else _make_guard

    monkeypatch.setattr(QMessageBox, "question", make("QMessageBox.question"))
    monkeypatch.setattr(QMessageBox, "warning", make("QMessageBox.warning"))
    monkeypatch.setattr(QMessageBox, "critical", make("QMessageBox.critical"))
    monkeypatch.setattr(QMessageBox, "information", make("QMessageBox.information"))

    monkeypatch.setattr(QMessageBox, "exec", make("QMessageBox.exec"))
    monkeypatch.setattr(QMessageBox, "exec_", make("QMessageBox.exec_"))
    monkeypatch.setattr(QDialog, "exec", make("QDialog.exec"))
    monkeypatch.setattr(QDialog, "exec_", make("QDialog.exec_"))
