"""Thin Qt per-game panel (#73, spec §7): the adaptive DS/HZD/FW panel. All logic is
Qt-free in game_panel_model (covered in test_game_panel_model); here we cover the widget's
hide-not-grey swap, the pickers' intents, the FW types.json grade, and the scope accessors.
Skips without [gui]."""
import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QFileDialog  # noqa: E402

from deciwaves.gui.views.game_panel import GamePanel  # noqa: E402

_CUDA_OK = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "ok", "message": "", "fix": ""}]}
_CUDA_ABSENT = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "unavailable", "message": "", "fix": ""}]}


# --- set_game: hide-not-grey per-game control swap -------------------------

def test_set_game_ds_shows_only_ds_controls(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert p.visible_controls() == {"transcript", "main_story"}


def test_set_game_hzd_shows_only_hzd_controls(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    assert p.visible_controls() == {"gpu", "sample_cap", "spine_only"}


def test_set_game_fw_shows_only_fw_controls(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    assert p.visible_controls() == {"gpu", "types_json", "gamescript", "tiers"}


def test_controls_are_hidden_not_disabled(qtbot):
    # spec §7: irrelevant controls are HIDDEN, never greyed. The DS main-story control widget
    # exists but is not visible under HZD, and is still enabled (not disabled).
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    assert "main_story" not in p.visible_controls()
    assert p._widgets["main_story"].isEnabled() is True   # hidden, not disabled


def test_scan_warning_text_swaps_per_game(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert "CPU" in p.scan_warning_text()
    p.set_game("hzd")
    assert "hours" in p.scan_warning_text()


# --- render_scope accessor per game ----------------------------------------

def test_render_scope_ds_default_main_story_off(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert p.render_scope() == {"main_story": False}
    p._main_story.setChecked(True)
    assert p.render_scope() == {"main_story": True}


def test_render_scope_hzd_spine_only(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    assert p.render_scope() == {"spine_only": False}


def test_render_scope_fw_tiers_default(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    assert p.render_scope() == {"tiers": "1,2,S"}


def test_fw_tiers_hint_label_is_visible(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    assert p._tiers_hint.isVisibleTo(p)
    assert "dropped" in p._tiers_hint.text()


def test_fw_tiers_hint_hidden_for_non_fw_games(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert not p._tiers_hint.isVisibleTo(p)
    p.set_game("hzd")
    assert not p._tiers_hint.isVisibleTo(p)


def test_fw_tiers_warning_on_unknown_token(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    assert not p._tiers_warning.isVisibleTo(p)
    p._tiers_edit.setText("1,2,Z")
    assert p._tiers_warning.isVisibleTo(p)
    assert "Z" in p._tiers_warning.text()
    assert "Unknown tier" in p._tiers_warning.text()


def test_fw_tiers_warning_hidden_for_valid_input(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    p._tiers_edit.setText("1,2,Z")
    assert p._tiers_warning.isVisibleTo(p)
    p._tiers_edit.setText("1,2,S")
    assert not p._tiers_warning.isVisibleTo(p)


def test_fw_tiers_warning_hidden_for_valid_subset_wd(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    p._tiers_edit.setText("W,D")
    assert not p._tiers_warning.isVisibleTo(p)


def test_fw_tiers_warning_cleared_on_game_reset(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    p._tiers_edit.setText("1,2,Z")
    assert p._tiers_warning.isVisibleTo(p)
    p.set_game("fw")
    assert not p._tiers_warning.isVisibleTo(p)


# --- sample cap (HZD) ------------------------------------------------------

def test_sample_cap_default_300_for_hzd_none_otherwise(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    assert p.sample_cap() == 300
    p.set_game("ds")
    assert p.sample_cap() is None   # non-HZD games have no cap to pass to process_argv


# --- FW types.json grade ---------------------------------------------------

def test_fw_types_status_reflects_missing_then_satisfied(qtbot, tmp_path):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    ws = str(tmp_path)
    p.set_context(ws, {}, None)
    assert "missing" in p.types_status_text().lower()
    open(os.path.join(ws, "types.json"), "w").close()
    p.set_context(ws, {}, None)
    assert "missing" not in p.types_status_text().lower()


# --- GPU/CUDA readiness label ----------------------------------------------

def test_gpu_label_reflects_cuda_payload(qtbot, tmp_path):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("hzd")
    p.set_context(str(tmp_path), {}, _CUDA_OK)
    assert "cuda" in p.gpu_status_text().lower() or "ready" in p.gpu_status_text().lower()
    p.set_context(str(tmp_path), {}, _CUDA_ABSENT)
    assert p.gpu_status_text() != ""


# --- Tooltips ---------------------------------------------------------------

def test_main_story_toggle_has_tooltip(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert p._main_story.toolTip(), "Main story toggle should have a non-empty tooltip"


def test_transcript_controls_have_tooltips(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    assert p._transcript_edit.toolTip(), "Transcript edit should have a non-empty tooltip"
    assert p._transcript_browse.toolTip(), "Transcript browse button should have a non-empty tooltip"
    assert p._reorder_btn.toolTip(), "Re-order button should have a non-empty tooltip"


def test_fw_pickers_have_tooltips(qtbot):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    assert p._types_edit.toolTip(), "Types edit should have a non-empty tooltip"
    assert p._types_browse.toolTip(), "Types browse button should have a non-empty tooltip"
    assert p._gamescript_edit.toolTip(), "Gamescript edit should have a non-empty tooltip"
    assert p._gamescript_browse.toolTip(), "Gamescript browse button should have a non-empty tooltip"


# --- picker intents (monkeypatch QFileDialog) ------------------------------

def test_ds_transcript_reorder_emits_intent(qtbot, tmp_path, monkeypatch):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("ds")
    picked = tmp_path / "story.md"
    picked.write_text("...", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(picked), "All (*.*)"))
    p._transcript_browse.click()
    with qtbot.waitSignal(p.transcript_order_requested) as blocker:
        p._reorder_btn.click()
    assert blocker.args == [os.path.abspath(str(picked))]


def test_fw_types_pick_emits_persist_intent(qtbot, tmp_path, monkeypatch):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    picked = tmp_path / "types.json"
    picked.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(picked), "JSON (*.json)"))
    with qtbot.waitSignal(p.types_picked) as blocker:
        p._types_browse.click()
    assert blocker.args == [str(picked)]


def test_fw_gamescript_pick_emits_persist_intent(qtbot, tmp_path, monkeypatch):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    picked = tmp_path / "gamescript.txt"
    picked.write_text("...", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(picked), "All (*.*)"))
    with qtbot.waitSignal(p.gamescript_picked) as blocker:
        p._gamescript_browse.click()
    assert blocker.args == [str(picked)]


def test_cancelled_pick_emits_nothing(qtbot, monkeypatch):
    p = GamePanel()
    qtbot.addWidget(p)
    p.set_game("fw")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    fired = []
    p.types_picked.connect(fired.append)
    p._types_browse.click()
    assert fired == []
