"""GUI entry-point dispatch (#67). These tests are Qt-free and MUST run without the
[gui] extra (no importorskip): they prove the CLI can decide whether to launch the GUI
and that `deciwaves.gui`'s public surface imports without PySide6."""
import importlib.util

from deciwaves import gui
from deciwaves.cli import main as cli_main


def test_is_available_matches_pyside6_presence():
    assert gui.is_available() == (importlib.util.find_spec("PySide6") is not None)


def test_gui_package_import_does_not_require_pyside6():
    # importing the package surface must succeed on a base install (Qt-free)
    import deciwaves.gui  # noqa: F401
    assert hasattr(gui, "launch") and hasattr(gui, "INSTALL_HINT")


def test_bare_launches_gui_when_available(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli_main, "_gui_is_available", lambda: True)
    monkeypatch.setattr("deciwaves.gui.launch",
                        lambda argv=None: calls.update(gui=True) or 0)
    monkeypatch.setattr("deciwaves.cli.guided.run_guided",
                        lambda *a, **k: calls.update(guided=True) or 0)
    assert cli_main.main([]) == 0
    assert calls == {"gui": True}


def test_bare_falls_back_to_guided_when_gui_absent(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli_main, "_gui_is_available", lambda: False)
    monkeypatch.setattr("deciwaves.cli.guided.run_guided",
                        lambda *a, **k: calls.update(guided=True) or 0)
    assert cli_main.main([]) == 0
    assert calls == {"guided": True}


def test_gui_subcommand_launches_when_available(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli_main, "_gui_is_available", lambda: True)
    monkeypatch.setattr("deciwaves.gui.launch",
                        lambda argv=None: calls.update(gui=True) or 0)
    assert cli_main.main(["gui"]) == 0
    assert calls == {"gui": True}


def test_gui_subcommand_hint_when_absent(monkeypatch, capsys):
    monkeypatch.setattr(cli_main, "_gui_is_available", lambda: False)
    rc = cli_main.main(["gui"])
    assert rc != 0
    assert 'pip install "deciwaves[gui]"' in capsys.readouterr().out
