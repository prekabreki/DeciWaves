"""The per-game panel wired into the shell (#73, spec §7): it mounts between the global bar
and the tab stack, swaps on game change, threads its render scope into Export MP3 and its
first-bind sample cap into Bind, runs the DS re-order as a standalone `ds order`, and persists
the FW BYO pickers through the setup path. Skips without [gui]."""
import csv
import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from deciwaves.gui import shell as shell_mod  # noqa: E402
from deciwaves.gui.shell import MainWindow  # noqa: E402

_CUDA_OK = {"ok": True, "checks": [
    {"name": "cuda", "ok": True, "status": "ok", "message": "", "fix": ""}]}


def _capture_jobs(w):
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    return calls


def test_game_panel_mounts_and_swaps_on_game_change(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.select_game("ds")
    assert w.game_panel.visible_controls() == {"transcript", "main_story"}
    w.bar.select_game("hzd")
    assert w.game_panel.visible_controls() == {"gpu", "sample_cap", "spine_only"}
    w.bar.select_game("fw")
    assert w.game_panel.visible_controls() == {"gpu", "types_json", "gamescript", "tiers"}


def test_export_threads_ds_main_story_scope(qtbot, tmp_path, monkeypatch):
    from deciwaves.games.ds.story_order import PLAYLIST_COLUMNS
    ws = str(tmp_path)
    pl = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(pl), exist_ok=True)
    with open(pl, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PLAYLIST_COLUMNS)
        w.writeheader()
        w.writerow(dict(episode="0", is_side="0", pos="0.0", section="0", scene="s",
                        line_index="0", track_index="0", category="cutscene", speaker="Sam",
                        subtitle="Hi.", stream_path="loc/a.wem.english.core.stream", line_id="a"))
    monkeypatch.setattr(shell_mod.config, "load", lambda: {"ds_install": r"C:\DS"})
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(ws)
    w.bar.select_game("ds")
    w.game_panel._main_story.setChecked(True)
    calls = _capture_jobs(w)
    w.library.export.export_mp3_requested.emit(96)
    assert calls and "--main-story" in calls[0]
    # regression guard: unchecked -> no --main-story (exactly the checked rows, #72).
    w.game_panel._main_story.setChecked(False)
    calls.clear()
    w.library.export.export_mp3_requested.emit(96)
    assert calls and "--main-story" not in calls[0]


def test_bind_threads_hzd_sample_cap(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("hzd")
    w.pipeline.setup_doctor.doctor.render_payload(_CUDA_OK)   # GPU present -> no dialog
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    w.game_panel._sample_cap.setValue(50)
    calls = _capture_jobs(w)
    w.pipeline.controls._bind_btn.click()
    argv = calls[0]
    assert argv[argv.index("--sample-cap") + 1] == "50"


def test_transcript_reorder_runs_standalone_order(qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game("ds")
    transcript = tmp_path / "story.md"
    transcript.write_text("...", encoding="utf-8")
    w.game_panel._transcript_edit.setText(str(transcript))
    calls = _capture_jobs(w)
    w.game_panel._reorder_btn.click()
    argv = calls[0]
    assert "order" in argv and "run" not in argv    # standalone order, never `ds run`
    assert argv[argv.index("--transcript") + 1] == os.path.abspath(str(transcript))


def test_fw_types_pick_persists_via_setup_path(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.select_game("fw")
    captured = {}

    def fake_run(*, force=False, skip_downloads=False, **paths):
        captured.update(paths)
        captured["skip_downloads"] = skip_downloads
        return True

    monkeypatch.setattr(w.pipeline.setup_doctor.setup, "run", fake_run)
    picked = str(tmp_path / "types.json")
    w.game_panel.types_picked.emit(picked)
    assert captured.get("fw_types") == picked   # persisted via setup, not a direct config.save
    assert captured["skip_downloads"] is True   # persist-only, no surprise tool fetch


def test_fw_gamescript_pick_persists_via_setup_path(qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.select_game("fw")
    captured = {}
    monkeypatch.setattr(w.pipeline.setup_doctor.setup, "run",
                        lambda **kw: captured.update(kw) or True)
    picked = str(tmp_path / "gamescript.txt")
    w.game_panel.gamescript_picked.emit(picked)
    assert captured.get("fw_gamescript") == picked
