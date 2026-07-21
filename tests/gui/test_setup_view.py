"""Setup screen + Doctor panel widgets (#68, spec §3). The parsing/severity rules are
covered Qt-free elsewhere; here we cover the widgets: rows render, severities re-grade on
game change, the buttons carry the right flags, spinners track running, and the real CLI
flows through end-to-end. Skips without [gui]."""
import sys

import pytest

pytest.importorskip("PySide6")
from deciwaves.gui.doctor_model import (  # noqa: E402
    SEV_ERROR,
    SEV_NEUTRAL,
    SEV_OK,
    SEV_WARN,
    DoctorItem,
)
from deciwaves.gui.views.setup import DoctorPanel, SetupDoctorView, SetupScreen  # noqa: E402

SLOW = "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.02)"

# a stand-in for `deciwaves ... setup` that prints a realistic summary + a WARNING
_FAKE_SETUP = (
    "print('DeciWaves setup summary:')\n"
    "print(f\"  {'tool':<10} {'status':<32} path\")\n"
    "print(f\"  {'ffmpeg':<10} {'fetched':<32} C:/x/ffmpeg.exe\")\n"
    "print('WARNING: oo2core_7_win64.dll not found under \\'C:/DS\\'.')\n"
)

_DOCTOR_PAYLOAD = {
    "ok": False,
    "checks": [
        {"name": "ds_install", "ok": False, "status": "broken",
         "message": "DS install: bad", "fix": "run deciwaves setup --ds-install <root>"},
        {"name": "hzd_package", "ok": True, "status": "not_configured",
         "message": "HZD package: not configured", "fix": ""},
        {"name": "asr_extra", "ok": True, "status": "unavailable",
         "message": "ASR extra: not installed", "fix": "pip install deciwaves[asr]"},
        {"name": "cuda", "ok": True, "status": "ok", "message": "CUDA: available", "fix": ""},
    ],
}


# --- DoctorPanel -----------------------------------------------------------

def test_doctor_panel_renders_a_row_per_check_with_severities(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    p.render_payload(_DOCTOR_PAYLOAD)
    assert len(p.items()) == 4
    assert p.severity_of("ds_install") == SEV_ERROR
    assert p.severity_of("hzd_package") == SEV_NEUTRAL
    assert p.severity_of("asr_extra") == SEV_WARN       # promoted for HZD (spec §3)
    assert p.severity_of("cuda") == SEV_OK


def test_doctor_panel_shows_fix_hints_verbatim(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    p.render_payload(_DOCTOR_PAYLOAD)
    assert "run deciwaves setup --ds-install <root>" in p.rendered_text()


def test_doctor_panel_regrades_on_game_change_without_a_new_run(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    p.render_payload(_DOCTOR_PAYLOAD)
    assert p.severity_of("asr_extra") == SEV_NEUTRAL    # DS: informational only
    p.set_game("fw")
    assert p.severity_of("asr_extra") == SEV_WARN       # re-graded, no subprocess


def test_doctor_panel_recheck_runs_the_real_cli(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.refreshed, timeout=30000):
        assert p.recheck() is True
    assert len(p.items()) > 0            # real `doctor --json` emitted its checks


def test_doctor_recheck_button_triggers_a_run(qtbot):
    # clicking exercises the real signal wiring: QAbstractButton.clicked emits a bool,
    # and the slot must tolerate it (or refreshed never fires and this times out).
    p = DoctorPanel(base=[sys.executable, "-c", "print('{\"ok\": true, \"checks\": []}')"])
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.refreshed, timeout=8000):
        p._recheck_btn.click()


def test_doctor_panel_parses_json_after_a_stdout_preamble(qtbot):
    # config-corruption warnings (config.load prints to stdout) and GPU import banners
    # can precede the JSON on stdout -- the panel must still find the checks, not blank out.
    p = DoctorPanel()
    qtbot.addWidget(p)
    preamble = "warning: config file C:/x/config.json is corrupted; ignoring it\n"
    payload = ('{"ok": true, "checks": '
               '[{"name": "ffmpeg", "ok": true, "status": "ok", "message": "m", "fix": ""}]}')
    p._on_finished(0, preamble + payload)
    assert [i.name for i in p.items()] == ["ffmpeg"]


def test_doctor_panel_survives_unparseable_and_non_object_output(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    p._on_finished(0, "totally not json")
    assert len(p.items()) == 1 and p.items()[0].status == "broken"
    p._on_finished(0, "[1, 2, 3]")   # valid JSON, wrong shape (not an object)
    assert len(p.items()) == 1 and p.items()[0].status == "broken"


# --- SetupScreen -----------------------------------------------------------

def test_setup_screen_parses_summary_and_warnings_on_finish(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", _FAKE_SETUP])
    qtbot.addWidget(s)
    with qtbot.waitSignal(s.finished, timeout=8000):
        assert s.run() is True
    assert "ffmpeg" in {r.label for r in s.rows()}
    assert any("oo2core" in w for w in s.warnings())


def test_redownload_button_forces_and_recheck_button_skips_downloads(qtbot, monkeypatch):
    s = SetupScreen(base=["py", "-c", "pass"])
    qtbot.addWidget(s)
    captured = []
    monkeypatch.setattr(s._runner, "start", lambda argv, cwd=None: captured.append(argv) or False)
    s._redownload_btn.click()
    s._recheck_btn.click()
    assert "--force" in captured[0]
    assert "--skip-downloads" in captured[1]


def test_setup_screen_is_busy_while_running_then_clears(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", SLOW])
    qtbot.addWidget(s)
    assert s.run() is True
    assert s.is_busy is True                 # indeterminate spinners on (spec §3)
    with qtbot.waitSignal(s.finished, timeout=8000):
        s.cancel()
    assert s.is_busy is False


# --- Tooltips ---------------------------------------------------------------

def test_doctor_recheck_button_has_tooltip(qtbot):
    p = DoctorPanel()
    qtbot.addWidget(p)
    assert p._recheck_btn.toolTip(), "Doctor Re-check button should have a non-empty tooltip"


def test_setup_buttons_have_tooltips(qtbot):
    s = SetupScreen()
    qtbot.addWidget(s)
    assert s._run_btn.toolTip(), "Run setup button should have a non-empty tooltip"
    assert s._redownload_btn.toolTip(), "Re-download button should have a non-empty tooltip"
    assert s._recheck_btn.toolTip(), "Re-check button should have a non-empty tooltip"


# --- Doctor auto-run on launch (#107) --------------------------------------

_FFMPEG_FAILED_SUMMARY = (
    "DeciWaves setup summary:\n"
    "  ffmpeg     FAILED: ffmpeg ([Errno 13] denied)  //nas/ffmpeg.exe\n"
)


def test_doctor_auto_checks_only_once(qtbot, monkeypatch):
    # auto_check() runs doctor the first time the panel becomes visible, then never again
    # on later show/hide cycles.
    p = DoctorPanel(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(p)
    calls = []
    monkeypatch.setattr(p, "recheck", lambda: (calls.append(1), True)[-1])
    assert p.auto_check() is True
    assert p.auto_check() is False
    assert calls == [1]


def test_doctor_auto_runs_on_first_show(qtbot):
    # showing the panel (as launch does) kicks a doctor run with no click -- so a healthy
    # install shows its statuses immediately instead of blank "-" placeholders.
    p = DoctorPanel(base=[sys.executable, "-c", 'print(\'{"ok": true, "checks": []}\')'])
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.refreshed, timeout=8000):
        p.show()


# --- Setup/Doctor status reconciliation (#110) -----------------------------

def test_regrade_downgrades_a_failed_tool_doctor_confirms_present(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    s._on_finished(0, _FFMPEG_FAILED_SUMMARY)
    assert s._tool_status["ffmpeg"].text().startswith("FAILED")     # red before reconcile
    s.regrade_against_doctor([DoctorItem("ffmpeg", True, "ok", "ffmpeg: x", "")])
    txt = s._tool_status["ffmpeg"].text()
    assert "FAILED" not in txt and "existing" in txt.lower()        # no longer contradicts


def test_regrade_leaves_a_genuinely_missing_tool_as_failed(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    s._on_finished(0, _FFMPEG_FAILED_SUMMARY)
    s.regrade_against_doctor([])                 # doctor doesn't confirm it -> stays FAILED
    assert s._tool_status["ffmpeg"].text().startswith("FAILED")


def test_regrade_restores_failed_text_when_a_softened_tool_goes_missing(qtbot):
    # WARN (present) -> ERROR (a later Re-check no longer confirms it) must not leave the
    # stale "using existing copy" text under a red row (#110 review finding).
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    s._on_finished(0, _FFMPEG_FAILED_SUMMARY)
    s.regrade_against_doctor([DoctorItem("ffmpeg", True, "ok", "ffmpeg: x", "")])
    assert "existing" in s._tool_status["ffmpeg"].text().lower()   # softened to amber
    s.regrade_against_doctor([])                                   # tool now gone
    txt = s._tool_status["ffmpeg"].text()
    assert "existing" not in txt.lower() and txt.startswith("FAILED")


def test_setup_doctor_view_reconciles_rows_when_doctor_refreshes(qtbot, monkeypatch):
    # the wire: a doctor refresh re-grades the setup rows so the two panels can't disagree.
    v = SetupDoctorView(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(v)
    monkeypatch.setattr(v.doctor, "recheck", lambda: True)   # don't spawn on setup.finished
    v.setup._on_finished(0, _FFMPEG_FAILED_SUMMARY)
    assert v.setup._tool_status["ffmpeg"].text().startswith("FAILED")
    import json
    v.doctor._on_finished(0, json.dumps({"ok": True, "checks": [
        {"name": "ffmpeg", "ok": True, "status": "ok", "message": "ffmpeg: x", "fix": ""}]}))
    txt = v.setup._tool_status["ffmpeg"].text()
    assert "FAILED" not in txt and "existing" in txt.lower()


# --- Label text-selectability (#108) ---------------------------------------

def test_labels_are_selectable(qtbot):
    from PySide6.QtWidgets import QLabel
    from PySide6.QtCore import Qt

    p = DoctorPanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    p.render_payload(_DOCTOR_PAYLOAD)
    for i in range(p._rows_layout.count()):
        row = p._rows_layout.itemAt(i).widget()
        for child in row.findChildren(QLabel):
            assert child.textInteractionFlags() & Qt.TextSelectableByMouse

    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    assert s._paths_label.textInteractionFlags() & Qt.TextSelectableByMouse
    assert s._warnings_label.textInteractionFlags() & Qt.TextSelectableByMouse
    for tool in ("vgmstream", "VGAudio", "ffmpeg"):
        assert s._tool_status[tool].textInteractionFlags() & Qt.TextSelectableByMouse


# --- M3: error row on non-zero exit, buttons disable/re-enable --------------

def test_setup_error_row_shows_on_nonzero_code_and_no_rows(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    s._on_finished(1, "totally garbled output with no summary rows")
    assert "setup exited with code 1" in s._paths_label.text()


def test_setup_buttons_disabled_while_busy(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", SLOW])
    qtbot.addWidget(s)
    assert s.run() is True
    assert s.is_busy is True
    assert s._run_btn.isEnabled() is False
    assert s._redownload_btn.isEnabled() is False
    assert s._recheck_btn.isEnabled() is False
    with qtbot.waitSignal(s.finished, timeout=8000):
        s.cancel()


def test_setup_buttons_re_enable_after_failed_run(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    s._on_finished(1, "totally garbled output with no summary rows")
    assert s._run_btn.isEnabled() is True
    assert s._redownload_btn.isEnabled() is True
    assert s._recheck_btn.isEnabled() is True
    assert s.is_busy is False


def test_setup_buttons_re_enable_after_cancelled_run(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", SLOW])
    qtbot.addWidget(s)
    assert s.run() is True
    with qtbot.waitSignal(s.finished, timeout=8000):
        s.cancel()
    assert s._run_btn.isEnabled() is True
    assert s._redownload_btn.isEnabled() is True
    assert s._recheck_btn.isEnabled() is True
    assert s.is_busy is False


def test_setup_buttons_re_enable_after_successful_run(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", _FAKE_SETUP])
    qtbot.addWidget(s)
    with qtbot.waitSignal(s.finished, timeout=8000):
        assert s.run() is True
    assert s._run_btn.isEnabled() is True
    assert s._redownload_btn.isEnabled() is True
    assert s._recheck_btn.isEnabled() is True


# --- M5: cancel button visibility -------------------------------------------

def test_setup_cancel_button_visible_while_busy(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", SLOW])
    qtbot.addWidget(s)
    assert s.run() is True
    assert s._cancel_btn.isVisibleTo(s) is True
    with qtbot.waitSignal(s.finished, timeout=8000):
        s.cancel()


def test_setup_cancel_button_hidden_when_idle(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(s)
    assert s._cancel_btn.isVisibleTo(s) is False


def test_setup_cancel_button_hidden_after_run_finishes(qtbot):
    s = SetupScreen(base=[sys.executable, "-c", _FAKE_SETUP])
    qtbot.addWidget(s)
    with qtbot.waitSignal(s.finished, timeout=8000):
        assert s.run() is True
    assert s._cancel_btn.isVisibleTo(s) is False


# --- M4: doctor placeholder and button disable during run -------------------

def test_doctor_shows_placeholder_when_started(qtbot):
    from PySide6.QtWidgets import QLabel
    p = DoctorPanel(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(p)
    p._on_started()
    texts = []
    for i in range(p._rows_layout.count()):
        w = p._rows_layout.itemAt(i).widget()
        if isinstance(w, QLabel):
            texts.append(w.text())
    assert any("Checking" in t for t in texts)


def test_doctor_recheck_disabled_while_running(qtbot):
    p = DoctorPanel(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(p)
    p._on_started()
    assert p._recheck_btn.isEnabled() is False


def test_doctor_recheck_re_enabled_after_finish(qtbot):
    p = DoctorPanel(base=[sys.executable, "-c", "pass"])
    qtbot.addWidget(p)
    p._on_started()
    assert p._recheck_btn.isEnabled() is False
    p._on_finished(0, '{"ok": true, "checks": []}')
    assert p._recheck_btn.isEnabled() is True
