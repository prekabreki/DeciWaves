"""Library view widget (#70, spec §6). Skips without the [gui-test] extra. Parsing/filter/
selection logic is covered Qt-free in test_library_model.py; here we assert the thin widget
wires the model to the table, status line, filters, and selection buttons -- via the test
accessors, not pixels."""
import csv
import os
import wave

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deciwaves.gui.library_model import load_selection  # noqa: E402
from deciwaves.gui.views.library import LibraryView  # noqa: E402


def _send_key(widget, key):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

DS_CAT = ["line_id", "core_path", "line_index", "category", "scene", "speaker_code",
          "speaker_name", "subtitle_en", "wem_path_en", "language"]
FW_FULL = ["line_id", "wav", "speaker", "subtitle", "gamescript_index", "quest", "tier",
           "score", "transcript"]


def _cat_row(**kw):
    base = dict(line_id="id", core_path="c", line_index="0", category="terminal",
                scene="sc", speaker_code="", speaker_name="Sam", subtitle_en="hi",
                wem_path_en="loc/x.wem.english", language="english")
    base.update(kw)
    return base


def _write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_ds_catalog(ws, rows):
    _write_csv(os.path.join(ws, "out", "catalog.csv"), DS_CAT, rows)


def _write_wav(path, seconds, framerate=8000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nframes = int(seconds * framerate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nframes)


def test_refresh_populates_rows_and_status(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b"), _cat_row(line_id="c")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    assert v.total_count() == 3
    assert v.visible_count() == 3
    assert v.checked_count() == 3
    assert v.status_text() == "3 checked · 3 visible · 3 total"
    assert [r.line_id for r in v.rows()] == ["a", "b", "c"]


def test_toggle_checkbox_changes_count_and_persists(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    idx = v._model.index(0, v._model.COL_CHECK)
    assert v._model.setData(idx, Qt.Unchecked, Qt.CheckStateRole) is True
    assert v.checked_count() == 1
    v._selection_timer.timeout.emit()        # flush debounce so disk reflects the toggle
    assert "a" in load_selection(ws, "ds")

    # reload from disk shows the persisted uncheck
    v2 = LibraryView()
    qtbot.addWidget(v2)
    v2.refresh("ds", ws)
    assert v2.checked_count() == 1
    assert "a" in v2._unchecked


def test_filter_changes_visible_not_checked_count(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", subtitle_en="hello there"),
                           _cat_row(line_id="b", subtitle_en="world")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._search.setText("hello")
    assert v.visible_count() == 1
    assert v.checked_count() == 2  # a filter never touches the selection


def test_selection_command_and_undo(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", subtitle_en=""),          # DS bark: no subtitle
                           _cat_row(line_id="b", subtitle_en="a real line")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    assert v.checked_count() == 2
    v._uncheck_barks_btn.click()
    assert v.checked_count() == 1
    assert "a" in load_selection(ws, "ds")
    v._undo_btn.click()
    assert v.checked_count() == 2
    assert load_selection(ws, "ds") == set()


def test_speaker_dropdown_populated(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", speaker_name="Sam"),
                           _cat_row(line_id="b", speaker_name="Amelie")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    items = [v._speaker.itemText(i) for i in range(v._speaker.count())]
    assert items == ["all", "Amelie", "Sam"]


def test_short_controls_disabled_without_lengths(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])  # DS carries no length
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    assert v._uncheck_short_btn.isEnabled() is False


def test_short_controls_enabled_with_fw_wav_lengths(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.0)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl",
                 "subtitle": "Hello", "gamescript_index": "1", "quest": "MQ", "tier": "S",
                 "score": "9", "transcript": "x"}])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("fw", ws)
    # Lengths start None (lazy) — short controls disabled until the background probe finishes.
    assert v._uncheck_short_btn.isEnabled() is False

    v._duration_pool.waitForDone()
    QApplication.processEvents()
    assert v._uncheck_short_btn.isEnabled() is True


def test_header_click_sorts(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", speaker_name="Zed"),
                           _cat_row(line_id="b", speaker_name="Al")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._on_header_clicked(v._model.COL_SPEAKER)  # sort by speaker asc
    assert v._model.row_at(0).speaker == "Al"


def test_preview_requested_emitted(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    idx = v._model.index(0, v._model.COL_PREVIEW)
    with qtbot.waitSignal(v.preview_requested) as blocker:
        v._on_cell_clicked(idx)
    assert blocker.args == ["a"]


def test_enter_key_previews_current_row(qtbot, tmp_path):
    """Enter on the current row emits preview_requested for it (spec §6.5 'enter plays')."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._table.setCurrentIndex(v._model.index(1, v._model.COL_ID))  # row "b"
    got = []
    v.preview_requested.connect(got.append)
    _send_key(v._table, Qt.Key_Return)
    assert got == ["b"]


def test_enter_key_on_unavailable_row_is_noop(qtbot, tmp_path):
    """Enter never previews an unavailable line (HZD pre-bind), same gate as clicking ▷."""
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "hzd", "catalog.csv"), DS_CAT,
               [_cat_row(line_id="h1", wem_path_en="")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("hzd", ws)
    v._table.setCurrentIndex(v._model.index(0, v._model.COL_ID))
    v.preview_requested.connect(lambda _lid: pytest.fail("unavailable row must not preview"))
    _send_key(v._table, Qt.Key_Return)


def test_space_key_toggles_current_row_checkbox(qtbot, tmp_path):
    """Space toggles the current row's checkbox from any column (spec §6.5 'space toggles')."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._table.setCurrentIndex(v._model.index(0, v._model.COL_ID))  # row "a", not the check col
    assert v.checked_count() == 2
    _send_key(v._table, Qt.Key_Space)
    assert v.checked_count() == 1
    v._selection_timer.timeout.emit()        # flush debounce so disk reflects the toggle
    assert "a" in load_selection(ws, "ds")
    _send_key(v._table, Qt.Key_Space)  # toggles back
    assert v.checked_count() == 2


def test_rapid_space_toggles_produce_one_disk_write(qtbot, tmp_path, monkeypatch):
    """Multiple rapid Space-toggles produce exactly one save_selection disk write."""
    import deciwaves.gui.views.library as lib_mod

    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b"), _cat_row(line_id="c")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._table.setCurrentIndex(v._model.index(0, v._model.COL_ID))

    calls = []
    monkeypatch.setattr(lib_mod, "save_selection", lambda *a: calls.append(1))

    # Three rapid toggles — no disk write during the barrage
    _send_key(v._table, Qt.Key_Space)
    _send_key(v._table, Qt.Key_Space)
    _send_key(v._table, Qt.Key_Space)
    assert len(calls) == 0

    # Flush the debounce — exactly one write
    v._selection_timer.timeout.emit()
    assert len(calls) == 1


def test_preview_column_availability_hzd_prebind_dimmed(qtbot, tmp_path):
    """HZD catalog-only (pre-bind): ▶ shows pending -- dimmed foreground + an
    'available after bind' tooltip (spec §6.2/§6.5) -- and clicking it is a no-op."""
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "hzd", "catalog.csv"), DS_CAT,
               [_cat_row(line_id="h1", wem_path_en="")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("hzd", ws)
    idx = v._model.index(0, v._model.COL_PREVIEW)
    assert v._model.data(idx, Qt.DisplayRole) == "▶"
    assert v._model.data(idx, Qt.ForegroundRole) is not None  # dimmed = unavailable
    assert v._model.data(idx, Qt.ToolTipRole) == "Preview available after bind"
    # clicking an unavailable ▷ never emits (playback is #71)
    v.preview_requested.connect(lambda _lid: pytest.fail("unavailable ▷ must not emit"))
    v._on_cell_clicked(idx)


def test_preview_column_availability_ds_and_fw_available(qtbot, tmp_path):
    """DS is always available; FW is available once a row has a WAV path -- available ▶ has
    no dim color and a 'Play preview' tooltip."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    idx = v._model.index(0, v._model.COL_PREVIEW)
    assert v._model.data(idx, Qt.ForegroundRole) is None
    assert v._model.data(idx, Qt.ToolTipRole) == "Play preview"

    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.0)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl", "subtitle": "Hello",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    v.refresh("fw", ws)
    idx = v._model.index(0, v._model.COL_PREVIEW)
    assert v._model.data(idx, Qt.ForegroundRole) is None
    assert v._model.data(idx, Qt.ToolTipRole) == "Play preview"


def test_fw_refresh_does_not_block_on_wav_probe(qtbot, tmp_path):
    """FW refresh must display rows immediately with length_s=None; the WAV probe runs
    on a background thread. This is the core H4 fix — the UI thread must never open
    tens of thousands of WAV headers synchronously."""
    ws = str(tmp_path)
    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.5)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl",
                 "subtitle": "Hello", "gamescript_index": "1", "quest": "MQ", "tier": "S",
                 "score": "9", "transcript": "x"}])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("fw", ws)
    # Rows appear immediately, lengths are None — no blocking WAV probe.
    assert v.total_count() == 1
    assert v.rows()[0].length_s is None
    assert v.visible_count() == 1
    # Length column shows "—" (None signal).
    idx = v._model.index(0, v._model.COL_LEN)
    assert v._model.data(idx, Qt.DisplayRole) == "—"


def test_fw_lengths_fill_via_background_pass(qtbot, tmp_path):
    """After the background QThreadPool worker finishes, lengths fill in and the model
    emits dataChanged for the length column so the table repaints progressively."""
    ws = str(tmp_path)
    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.5)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl",
                 "subtitle": "Hello", "gamescript_index": "1", "quest": "MQ", "tier": "S",
                 "score": "9", "transcript": "x"}])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("fw", ws)
    assert v.rows()[0].length_s is None

    # Wait for the background probe and flush queued signals.
    v._duration_pool.waitForDone()
    QApplication.processEvents()

    assert v.rows()[0].length_s is not None
    assert abs(v.rows()[0].length_s - 1.5) < 0.01
    # Short controls should be enabled now that lengths are known.
    assert v._uncheck_short_btn.isEnabled() is True
    idx = v._model.index(0, v._model.COL_LEN)
    assert v._model.data(idx, Qt.DisplayRole) != "—"


def test_stale_duration_task_results_are_dropped(qtbot, tmp_path, monkeypatch):
    """When refresh() fires while a prior duration probe is still in flight, the stale
    result must be discarded — the generation tag prevents double-population and races."""
    ws = str(tmp_path)
    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.0)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl",
                 "subtitle": "Hello", "gamescript_index": "1", "quest": "MQ", "tier": "S",
                 "score": "9", "transcript": "x"}])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("fw", ws)

    # Capture the generation that the first task sees.
    gen_before = v._duration_generation

    # Second refresh bumps generation again (simulates rapid refresh before probe finishes).
    v.refresh("fw", ws)
    assert v._duration_generation == gen_before + 1

    # Simulate a stale result arriving for the old generation — it must be discarded.
    v._on_durations_ready(gen_before, {"f1": 5.0})
    # The rows should NOT have length 5.0 — the stale result was dropped.
    assert v.rows()[0].length_s is None  # fresh refresh also started with None

    # After the current generation's probe finishes, lengths are correct.
    v._duration_pool.waitForDone()
    QApplication.processEvents()
    assert v.rows()[0].length_s == 1.0


def test_empty_state_overlay(qtbot, tmp_path):
    """No catalog yet → overlay says 'No catalog yet'."""
    v = LibraryView()
    qtbot.addWidget(v)
    assert v._table.overlay_text == "No catalog yet — run Scan on the Pipeline tab"


def test_no_results_overlay_disappears_with_rows(qtbot, tmp_path):
    """Overlay is None when rows are visible, 'No lines match' when filtered out."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", subtitle_en="hello")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    assert v._table.overlay_text is None

    v._search.setText("zzz_nonexistent")
    assert v.visible_count() == 0
    assert v._table.overlay_text == "No lines match — [Clear filters]"


def test_filter_state_resets_on_game_change_but_persists_same_game(qtbot, tmp_path):
    """Switching games drops the prior game's stray search/sort/toggles (spec §6 -- the list
    is per-game); a same-game refresh (job-finished) preserves all filter/sort state."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", speaker_name="Zed", subtitle_en="hello there")])
    _write_csv(os.path.join(ws, "out", "hzd", "catalog.csv"), DS_CAT,
               [_cat_row(line_id="h", subtitle_en="world")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._search.setText("hello")
    v._hide_dupes.setChecked(True)
    v._hide_nosub.setChecked(True)
    v._on_header_clicked(v._model.COL_SPEAKER)
    assert v._sort_key == "speaker"

    # DS -> HZD: filters/sort reset to defaults
    v.refresh("hzd", ws)
    assert v._search.text() == ""
    assert v._hide_dupes.isChecked() is False
    assert v._hide_nosub.isChecked() is False
    assert v._sort_key is None and v._sort_desc is False

    # same-game refresh (e.g. job-finished): filter state preserved
    v._search.setText("world")
    v._hide_dupes.setChecked(True)
    v.refresh("hzd", ws)
    assert v._search.text() == "world"
    assert v._hide_dupes.isChecked() is True


def test_flush_pending_selection_saves_inside_debounce_window(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    assert v.checked_count() == 2

    # Toggle a row — debounce timer starts, no disk write yet
    idx = v._model.index(0, v._model.COL_CHECK)
    assert v._model.setData(idx, Qt.Unchecked, Qt.CheckStateRole) is True
    assert v._selection_timer.isActive()

    # Flush pending — persists immediately without waiting for the 150 ms timer
    v.flush_pending_selection()
    assert not v._selection_timer.isActive()
    assert "a" in load_selection(ws, "ds")
    assert v.checked_count() == 1

    # Second call is a strict no-op (no pending save)
    v.flush_pending_selection()
