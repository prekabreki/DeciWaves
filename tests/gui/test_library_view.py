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
from PySide6.QtGui import QAccessible, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deciwaves.gui.library_model import STORY_ORDER_HINT, load_selection  # noqa: E402
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
    v._wait_for_parse()
    assert v.total_count() == 3
    assert v.visible_count() == 3
    assert v.checked_count() == 3
    assert v.status_text() == "3 checked · 3 visible · 3 total · story order"
    assert [r.line_id for r in v.rows()] == ["a", "b", "c"]


def test_toggle_checkbox_changes_count_and_persists(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
    idx = v._model.index(0, v._model.COL_CHECK)
    assert v._model.setData(idx, Qt.Unchecked, Qt.CheckStateRole) is True
    assert v.checked_count() == 1
    v._selection_timer.timeout.emit()        # flush debounce so disk reflects the toggle
    assert "a" in load_selection(ws, "ds")

    # reload from disk shows the persisted uncheck
    v2 = LibraryView()
    qtbot.addWidget(v2)
    v2.refresh("ds", ws)
    v2._wait_for_parse()
    assert v2.checked_count() == 1
    assert "a" in v2._unchecked


def test_filter_changes_visible_not_checked_count(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", subtitle_en="hello there"),
                           _cat_row(line_id="b", subtitle_en="world")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
    items = [v._speaker.itemText(i) for i in range(v._speaker.count())]
    assert items == ["all", "Amelie", "Sam"]


def test_short_controls_disabled_without_lengths(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])  # DS carries no length
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
    v._on_header_clicked(v._model.COL_SPEAKER)  # sort by speaker asc
    assert v._model.row_at(0).speaker == "Al"


def test_preview_requested_emitted(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
    idx = v._model.index(0, v._model.COL_PREVIEW)
    assert v._model.data(idx, Qt.ForegroundRole) is None
    assert v._model.data(idx, Qt.ToolTipRole) == "Play preview"

    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.0)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl", "subtitle": "Hello",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    v.refresh("fw", ws)
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()
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
    v._wait_for_parse()

    # Capture the generation that the first task sees.
    gen_before = v._duration_generation

    # Second refresh bumps generation again (simulates rapid refresh before probe finishes).
    v.refresh("fw", ws)
    v._wait_for_parse()
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
    """No catalog yet → a real overlay widget says 'No catalog yet', exposed to the
    accessibility tree, with no 'Clear filters' button."""
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", str(tmp_path))
    v._wait_for_parse()
    overlay = v._table._overlay
    assert v._table.overlay_text == "No catalog yet — run Scan on the Pipeline tab"
    assert not overlay.isHidden()
    assert overlay._label.text() == "No catalog yet — run Scan on the Pipeline tab"
    assert overlay._label.accessibleName() == "No catalog yet — run Scan on the Pipeline tab"
    assert overlay._clear.isHidden()
    # accessible via QAccessible, not just widget state
    acc = QAccessible.queryAccessibleInterface(overlay._label)
    assert acc is not None
    assert acc.text(QAccessible.Name) == "No catalog yet — run Scan on the Pipeline tab"


def test_no_results_overlay_disappears_with_rows(qtbot, tmp_path):
    """Overlay is hidden when rows are visible (never intercepting clicks), and shows the
    no-results message plus a focusable 'Clear filters' button when filtered out."""
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a", subtitle_en="hello")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
    assert v._table.overlay_text is None
    assert v._table._overlay.isHidden()

    v._search.setText("zzz_nonexistent")
    assert v.visible_count() == 0
    overlay = v._table._overlay
    assert v._table.overlay_text == "No lines match —"
    assert not overlay.isHidden()
    assert overlay._label.text() == "No lines match —"
    # amber (a filter hit), not the grey of the empty-catalog state
    assert overlay._AMBER in overlay._label.styleSheet()
    assert overlay._GREY not in overlay._label.styleSheet()
    # real, focusable button reachable by keyboard
    assert not overlay._clear.isHidden()
    assert overlay._clear.isEnabled()
    assert overlay._clear.text() == "Clear filters"
    assert overlay._clear.accessibleName() == "Clear filters"
    assert (overlay._clear.focusPolicy() & Qt.TabFocus) != 0
    acc = QAccessible.queryAccessibleInterface(overlay._label)
    assert acc is not None
    assert acc.text(QAccessible.Name) == "No lines match —"

    # the button clears the filter and the overlay disappears with the rows
    overlay._clear.click()
    v._debounce_timer.timeout.emit()   # flush the search debounce
    assert v.visible_count() == 1
    assert v._table._overlay.isHidden()


def test_empty_state_overlay_geometries_follow_viewport(qtbot, tmp_path):
    """The overlay is pinned to the viewport and resizes with it (never drifting off after
    scrollbars appear)."""
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", str(tmp_path))
    v._wait_for_parse()
    overlay = v._table._overlay
    assert overlay.geometry() == v._table.viewport().rect()
    # once shown (real usage), the overlay stays pinned and follows live viewport resizes
    with qtbot.waitExposed(v):
        v.show()
    assert overlay.geometry() == v._table.viewport().rect()
    v._table.resize(800, 600)
    qtbot.wait(50)
    QApplication.processEvents()
    assert overlay.geometry() == v._table.viewport().rect()


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
    v._wait_for_parse()
    v._search.setText("hello")
    v._hide_dupes.setChecked(True)
    v._hide_nosub.setChecked(True)
    v._on_header_clicked(v._model.COL_SPEAKER)
    assert v._sort_key == "speaker"

    # DS -> HZD: filters/sort reset to defaults
    v.refresh("hzd", ws)
    v._wait_for_parse()
    assert v._search.text() == ""
    assert v._hide_dupes.isChecked() is False
    assert v._hide_nosub.isChecked() is False
    assert v._sort_key is None and v._sort_desc is False

    # same-game refresh (e.g. job-finished): filter state preserved
    v._search.setText("world")
    v._hide_dupes.setChecked(True)
    v.refresh("hzd", ws)
    v._wait_for_parse()
    assert v._search.text() == "world"
    assert v._hide_dupes.isChecked() is True


def test_flush_pending_selection_saves_inside_debounce_window(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])
    v = LibraryView()
    qtbot.addWidget(v)
    v.refresh("ds", ws)
    v._wait_for_parse()
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


# --- set_job_running banner (#278) -------------------------------------------


def test_set_job_running_shows_and_hides_banner(qtbot):
    v = LibraryView()
    qtbot.addWidget(v)
    v.set_job_running(True)
    assert not v._job_running_banner.isHidden()
    assert "this list may change" in v._job_running_banner.text()
    v.set_job_running(False)
    assert v._job_running_banner.isHidden()


def test_table_stays_enabled_while_job_running(qtbot):
    v = LibraryView()
    qtbot.addWidget(v)
    v.set_job_running(True)
    assert v._table.isEnabled()


def test_story_order_hint_shown_for_ds_only(qtbot, tmp_path):
    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a")])
    _write_csv(os.path.join(ws, "out", "hzd", "catalog.csv"), DS_CAT,
               [_cat_row(line_id="h")])
    _write_wav(os.path.join(ws, "out", "fw", "audio", "f1.wav"), seconds=1.0)
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": "audio/f1.wav", "speaker": "Varl",
                 "subtitle": "Hello", "gamescript_index": "1", "quest": "MQ", "tier": "S",
                 "score": "9", "transcript": "x"}])
    v = LibraryView()
    qtbot.addWidget(v)

    v.refresh("ds", ws)
    v._wait_for_parse()
    assert not v._story_order_hint.isHidden()
    assert v._story_order_hint.text() == STORY_ORDER_HINT

    v.refresh("hzd", ws)
    v._wait_for_parse()
    assert v._story_order_hint.isHidden()

    v.refresh("fw", ws)
    v._wait_for_parse()
    assert v._story_order_hint.isHidden()


def test_unset_workspace_does_not_call_load_or_save_against_dot(qtbot, monkeypatch):
    """With workspace unset, load_lines/selection-save are never called against '.' (#294)."""
    import deciwaves.gui.library_model as lib_model

    load_calls = []
    save_calls = []
    monkeypatch.setattr(lib_model, "load_lines",
                        lambda ws, g: load_calls.append(ws) or [])
    monkeypatch.setattr(lib_model, "load_selection",
                        lambda ws, g: set())
    monkeypatch.setattr(lib_model, "save_selection",
                        lambda ws, g, u: save_calls.append(ws))

    v = LibraryView()
    qtbot.addWidget(v)

    # refresh with empty workspace must not call load_lines at all
    v.refresh("ds", "")
    v._wait_for_parse()
    assert load_calls == []

    # flush/apply selection with empty workspace must not call save_selection
    v._flush_selection()
    v._apply_selection({"a"})
    assert save_calls == []

    # debounced selection timer fires — still no save against empty workspace
    v._selection_timer.timeout.emit()
    assert save_calls == []


def test_superseded_parse_does_not_overwrite_rows(qtbot, tmp_path, monkeypatch):
    """When two refreshes fire in rapid succession, the stale first parse must not
    overwrite the rows set by the second (newer) parse. The stub blocks the first
    call so it consistently finishes *after* the second, exercising the generation
    guard in ``_on_lines_loaded``.

    This test patches ``load_lines`` where it is *used* in ``views.library``
    (``_ParseTask.run`` calls the module-local import, not the original name in
    ``library_model``). It also asserts ``call_count == 2`` so the test can never
    silently degrade to a no-op.  The non-blocking path is verified first so a
    basic refresh still works end-to-end."""
    import threading
    import time

    from deciwaves.gui.library_model import LineRow, load_lines as real_load_lines

    ws = str(tmp_path)
    _write_ds_catalog(ws, [_cat_row(line_id="a"), _cat_row(line_id="b")])

    call_count = [0]
    first_block = threading.Event()
    second_done = threading.Event()

    def blocking_load(workspace, game):
        call_count[0] += 1
        if call_count[0] == 1:
            first_block.wait()
            return [LineRow(line_id="STALE")]
        else:
            result = real_load_lines(workspace, game)
            second_done.set()
            return result

    monkeypatch.setattr("deciwaves.gui.views.library.load_lines", blocking_load)

    v = LibraryView()
    qtbot.addWidget(v)

    try:
        # First refresh: parse is dispatched, blocks inside blocking_load
        v.refresh("ds", ws)

        # Wait until the first call is inside the stub (call_count bumped to 1).
        while call_count[0] == 0:
            QApplication.processEvents()
            time.sleep(0.001)
        assert call_count[0] == 1

        # Second refresh: supersedes the first.
        v.refresh("ds", ws)

        # Wait for the second parse to finish and be processed on the main thread.
        assert second_done.wait(10), "second_done.wait() timed out"

        # second_done fires INSIDE the stub -- i.e. BEFORE _ParseTask.run emits its Qt
        # signal -- so the event has not necessarily been delivered yet (issue #346:
        # asserting straight after the wait flaked ~1 full-suite run in 6). Poll for the
        # result to actually be APPLIED, with a bounded deadline, rather than assuming
        # one processEvents() pass is enough. Only the second parse can land here: the
        # first is still held on first_block, so this cannot swallow the stale result.
        deadline = time.monotonic() + 5
        while v.total_count() == 0 and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.001)
        assert v.total_count() != 0, "second parse was never applied within 5s"

        assert call_count[0] == 2  # the stub actually ran twice

        # Verify the second (non-stale) parse populated the view correctly.
        assert v.total_count() == 2
        assert v.rows()[0].line_id == "a"

        # Now unblock the stale first parse. Its result carries line_id="STALE"
        # and a stale generation — _on_lines_loaded must discard it.
        first_block.set()
        QApplication.processEvents()
        time.sleep(0.1)
        QApplication.processEvents()

        # The view must still reflect the second (non-stale) parse.
        assert v.total_count() == 2
        assert v.rows()[0].line_id == "a"
        assert v.rows()[0].line_id != "STALE"
        assert call_count[0] == 2
    finally:
        first_block.set()
        QApplication.processEvents()
        assert v._parse_pool.waitForDone(5000), "worker thread leaked"
