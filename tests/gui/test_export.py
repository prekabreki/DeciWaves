"""Thin Qt Export panel + batch Dump-WAV worker (#72, spec §8). Skips without [gui-test].

The export building blocks are Qt-free and covered in test_export_model.py; here we assert the
widget glue: button enable/disable gating, the DS-only bitrate combo (truth-in-labeling), the
three intent signals (with QFileDialog monkeypatched -- no real dialog), and the batch dump
worker (fake resolver, no real decode / audio device: CI has neither) copying WAVs with
progress, skipping+counting a per-row failure, and cancelling early.
"""
import os

import pytest

pytest.importorskip("PySide6")

from deciwaves.gui.export import (  # noqa: E402
    DumpRunner, ExportPanel,
    _CatalogCopySignals, _CatalogCopyWorker,
    _DumpSignals, _DumpWorker,
)
from deciwaves.gui.preview_model import PreviewError  # noqa: E402


# --- ExportPanel: gating + labeling ----------------------------------------

def _ctx(panel, *, game="ds", checked=3, can_mp3=True, can_catalog=True, running=False):
    panel.set_context(game, ".", checked, can_mp3, can_catalog)
    panel.set_running(running)


def test_buttons_disabled_when_nothing_checked(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=0)
    assert p.mp3_enabled() is False
    assert p.dump_enabled() is False
    assert p.catalog_enabled() is False


def test_buttons_disabled_while_running(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=5, running=True)
    assert p.mp3_enabled() is False
    assert p.dump_enabled() is False
    assert p.catalog_enabled() is False


def test_export_mp3_needs_render_input(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=5, can_mp3=False)
    assert p.mp3_enabled() is False       # no playlist/manifest yet
    assert p.dump_enabled() is True       # dump works off the preview path, needs no render input


def test_catalog_needs_a_source(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=5, can_catalog=False)
    assert p.catalog_enabled() is False


def test_all_enabled_when_ready(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=5)
    assert (p.mp3_enabled(), p.dump_enabled(), p.catalog_enabled()) == (True, True, True)


def test_bitrate_combo_ds_only(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, game="ds")
    assert p.bitrate_visible() is True
    assert p.bitrate() == 128            # default
    _ctx(p, game="hzd")
    assert p.bitrate_visible() is False  # HZD/FW are hardcoded 128k (spec §8.2)
    assert p.bitrate() == 128
    _ctx(p, game="fw")
    assert p.bitrate_visible() is False


# --- ExportPanel: intent signals -------------------------------------------

def test_export_mp3_signal_carries_bitrate(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, game="ds")
    p._bitrate.setCurrentText("192")
    with qtbot.waitSignal(p.export_mp3_requested) as blocker:
        p._mp3_btn.click()
    assert blocker.args == [192]


def test_dump_signal_uses_monkeypatched_dialog(qtbot, monkeypatch, tmp_path):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=2)
    monkeypatch.setattr("deciwaves.gui.export.QFileDialog.getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    with qtbot.waitSignal(p.dump_wav_requested) as blocker:
        p._dump_btn.click()
    assert blocker.args == [str(tmp_path)]


def test_dump_dialog_cancel_emits_nothing(qtbot, monkeypatch):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=2)
    monkeypatch.setattr("deciwaves.gui.export.QFileDialog.getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))     # user cancelled
    fired = []
    p.dump_wav_requested.connect(fired.append)
    p._dump_btn.click()
    assert fired == []


def test_catalog_signal_uses_monkeypatched_dialog(qtbot, monkeypatch, tmp_path):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=2)
    dest = str(tmp_path / "catalog.csv")
    monkeypatch.setattr("deciwaves.gui.export.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (dest, "CSV (*.csv)")))
    with qtbot.waitSignal(p.export_catalog_requested) as blocker:
        p._catalog_btn.click()
    assert blocker.args == [dest]


def test_dump_button_becomes_cancel_while_dumping(qtbot):
    p = ExportPanel(); qtbot.addWidget(p)
    _ctx(p, checked=2)
    p.set_running(True)          # a job is in progress...
    p.set_dumping(True)          # ...and it's this panel's dump -> the button offers Cancel
    assert "cancel" in p._dump_btn.text().lower()
    assert p._dump_btn.isEnabled() is True
    fired = []
    p.dump_cancel_requested.connect(lambda: fired.append(True))
    p._dump_btn.click()
    assert fired == [True]


# --- batch Dump-WAV worker -------------------------------------------------

class _FakeResolver:
    """Writes a tiny real WAV per line so the worker's copy has something to copy."""

    def __init__(self, wav_dir, boom=frozenset()):
        self._dir = str(wav_dir)
        self._boom = set(boom)
        os.makedirs(self._dir, exist_ok=True)

    def resolve_wav(self, line_id, audio_path):
        if line_id in self._boom:
            raise PreviewError(f"no clip for {line_id}")
        path = os.path.join(self._dir, f"src_{line_id}.wav")
        with open(path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 40)
        return path


def _run_worker(worker):
    """Drive the QRunnable's run() synchronously (no thread pool) and collect its signals."""
    progress, failures, done = [], [], []
    worker._signals.progress.connect(lambda d, t: progress.append((d, t)))
    worker._signals.row_failed.connect(lambda lid, m: failures.append(lid))
    worker._signals.finished.connect(lambda ok, bad: done.append((ok, bad)))
    worker.run()
    return progress, failures, done


def test_dump_worker_copies_each_checked_row(qtbot, tmp_path):
    resolver = _FakeResolver(tmp_path / "src")
    dest = tmp_path / "dest"
    rows = [("a", None), ("b", None), ("c", None)]
    signals = _DumpSignals()          # a bare signals holder for the standalone worker
    progress, failures, done = _run_worker(_DumpWorker(resolver, rows, str(dest), signals))
    assert done == [(3, 0)]
    assert failures == []
    assert progress[-1] == (3, 3)
    assert sorted(os.listdir(dest)) == ["a.wav", "b.wav", "c.wav"]


def test_dump_worker_skips_and_counts_a_row_failure(qtbot, tmp_path):
    resolver = _FakeResolver(tmp_path / "src", boom={"b"})
    dest = tmp_path / "dest"
    rows = [("a", None), ("b", None), ("c", None)]
    signals = _DumpSignals()
    progress, failures, done = _run_worker(_DumpWorker(resolver, rows, str(dest), signals))
    assert done == [(2, 1)]           # b failed, batch continued
    assert failures == ["b"]
    assert sorted(os.listdir(dest)) == ["a.wav", "c.wav"]


def test_dump_worker_cancel_stops_early(qtbot, tmp_path):
    resolver = _FakeResolver(tmp_path / "src")
    dest = tmp_path / "dest"
    rows = [("a", None), ("b", None), ("c", None)]
    signals = _DumpSignals()
    worker = _DumpWorker(resolver, rows, str(dest), signals)
    worker.cancel()                   # cancel before it runs -> processes nothing
    _progress, _failures, done = _run_worker(worker)
    ok, bad = done[0]
    assert ok == 0 and bad == 0
    assert not os.path.exists(dest) or os.listdir(dest) == []


def test_dump_worker_disambiguates_colliding_safe_names(qtbot, tmp_path):
    """Two distinct ``line_id`` values that map to the same ``_safe_name`` output (e.g.
    ``"foo bar"`` and ``"foo_bar"`` both become ``foo_bar``) must each produce a distinct
    file on disk, and ``ok`` must reflect both -- no silent overwrite (issue #102)."""
    resolver = _FakeResolver(tmp_path / "src")
    dest = tmp_path / "dest"
    rows = [("foo bar", None), ("foo_bar", None)]
    signals = _DumpSignals()
    progress, failures, done = _run_worker(_DumpWorker(resolver, rows, str(dest), signals))
    assert done == [(2, 0)]
    assert failures == []
    files = sorted(os.listdir(dest))
    assert files == ["foo_bar.wav", "foo_bar_1.wav"]


def test_dump_worker_mid_batch_cancel_stops_early(qtbot, tmp_path):
    # The prior cancel test cancels BEFORE run(); here the flag is tripped BETWEEN rows,
    # so the loop's next-iteration guard must stop the batch with rows still unprocessed.
    dest = tmp_path / "dest"
    rows = [("a", None), ("b", None), ("c", None)]
    signals = _DumpSignals()
    holder = {}

    class _CancelAfterFirst:
        """Resolves row 1 normally, then trips the worker's cancel flag mid-row."""

        def __init__(self, wav_dir):
            self._dir = str(wav_dir)
            os.makedirs(self._dir, exist_ok=True)
            self.n = 0

        def resolve_wav(self, line_id, audio_path):
            self.n += 1
            path = os.path.join(self._dir, f"src_{line_id}.wav")
            with open(path, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 40)
            if self.n == 1:
                holder["worker"].cancel()      # cancel BETWEEN row 1 and row 2
            return path

    resolver = _CancelAfterFirst(tmp_path / "src")
    worker = _DumpWorker(resolver, rows, str(dest), signals)
    holder["worker"] = worker
    _progress, failures, done = _run_worker(worker)
    assert done == [(1, 0)]                     # only row 1 completed
    assert resolver.n == 1                       # row 2 never resolved -> stopped early
    assert failures == []
    assert sorted(os.listdir(dest)) == ["a.wav"]


def test_dump_runner_start_is_single_flight(qtbot, tmp_path):
    resolver = _FakeResolver(tmp_path / "src")
    runner = DumpRunner()
    done = []
    runner.finished.connect(lambda ok, bad: done.append((ok, bad)))
    with qtbot.waitSignal(runner.finished, timeout=3000):
        assert runner.start(resolver, [("a", None), ("b", None)], str(tmp_path / "d")) is True
    assert done == [(2, 0)]
    assert runner.is_running is False


# --- shell wiring ----------------------------------------------------------

def _mainwindow(qtbot, tmp_path, game):
    from deciwaves.gui.shell import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.bar.set_workspace(str(tmp_path))
    w.bar.select_game(game)
    return w


def _make_ds_playlist(ws):
    import csv as _csv
    from deciwaves.games.ds.story_order import PLAYLIST_COLUMNS
    path = os.path.join(ws, "out", "playlist.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=PLAYLIST_COLUMNS)
        w.writeheader()
        w.writerow(dict(episode="0", is_side="0", pos="0.0", section="0", scene="s",
                        line_index="0", track_index="0", category="cutscene", speaker="Sam",
                        subtitle="Hi.", stream_path="loc/a.wem.english.core.stream", line_id="a"))


def test_shell_export_mp3_writes_selection_and_starts_runner(qtbot, tmp_path, monkeypatch):
    ws = str(tmp_path)
    _make_ds_playlist(ws)
    w = _mainwindow(qtbot, tmp_path, "ds")
    monkeypatch.setattr("deciwaves.gui.shell.config.load", lambda: {"ds_install": r"C:\DS"})
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True

    w.library.export.export_mp3_requested.emit(96)

    assert calls, "expected the render job to be started on the single runner"
    argv = calls[0]
    assert "render" in argv and "--playlist" in argv and "--bitrate" in argv
    assert argv[argv.index("--bitrate") + 1] == "96"
    assert w._job_kind == "export"
    # the filtered selection was actually written
    assert os.path.isfile(os.path.join(ws, "out", "ds", "gui", "render-selection.csv"))


def test_shell_export_mp3_surfaces_error_without_starting(qtbot, tmp_path, monkeypatch):
    # DS render input exists but the install is unconfigured -> ExportError, no job.
    ws = str(tmp_path)
    _make_ds_playlist(ws)
    w = _mainwindow(qtbot, tmp_path, "ds")
    monkeypatch.setattr("deciwaves.gui.shell.config.load", lambda: {})
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    w.library.export.export_mp3_requested.emit(128)
    assert calls == []
    assert "not configured" in w.pipeline.log_text().lower()


def test_shell_export_finish_reports_success_vs_failure(qtbot, tmp_path):
    w = _mainwindow(qtbot, tmp_path, "ds")
    w._job_kind = "export"
    w._job_game = "ds"
    w._on_job_finished(0)
    assert "export" in w.pipeline.log_text().lower()
    log_after_success = w.pipeline.log_text()

    w._job_kind = "export"
    w._job_game = "ds"
    w._on_job_finished(1)
    new = w.pipeline.log_text()[len(log_after_success):]
    assert "fail" in new.lower() or "error" in new.lower()


def test_shell_catalog_copy(qtbot, tmp_path):
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    ws = str(tmp_path)
    src = os.path.join(ws, "out", "catalog.csv")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write("line_id\na\n")
    w = _mainwindow(qtbot, tmp_path, "ds")
    dest = os.path.join(ws, "exported-catalog.csv")
    w.library.export.export_catalog_requested.emit(dest)
    QThreadPool.globalInstance().waitForDone()
    QApplication.processEvents()
    assert os.path.isfile(dest)
    assert open(dest, encoding="utf-8").read() == "line_id\na\n"


def test_shell_catalog_missing_source_messages(qtbot, tmp_path):
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    w = _mainwindow(qtbot, tmp_path, "fw")
    w.library.export.export_catalog_requested.emit(os.path.join(str(tmp_path), "x.csv"))
    QThreadPool.globalInstance().waitForDone()
    QApplication.processEvents()
    assert "catalog" in w.pipeline.log_text().lower()


def test_shell_dump_starts_batch_and_excludes_pipeline(qtbot, tmp_path, monkeypatch):
    _make_ds_playlist(str(tmp_path))       # a checked row must exist to dump
    w = _mainwindow(qtbot, tmp_path, "ds")
    started = []

    def _fake_start(resolver, rows, dest):
        started.append((rows, dest))
        w.dump._running = True             # mirror DumpRunner.start flipping is_running
        return True

    monkeypatch.setattr(w.dump, "start", _fake_start)
    w.library.export.dump_wav_requested.emit(str(tmp_path / "dumpdir"))
    assert started, "expected the dump batch to start on the thread pool"
    # While the dump runs the pipeline is mutually excluded (spec §5.3): both the
    # Scan/Bind controls AND the stage-strip Re-run affordance are disabled.
    assert w.pipeline.controls._scan_btn.isEnabled() is False
    assert w.pipeline.strip.rerun_enabled() is False


def test_shell_dump_running_blocks_pipeline_start(qtbot, tmp_path):
    # A live dump must refuse a pipeline start even if the handler is invoked directly
    # (e.g. via the strip's context menu) -- runner.start must never be reached.
    w = _mainwindow(qtbot, tmp_path, "ds")
    w.dump._running = True                  # a dump batch is live (is_running -> True)
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    w._on_scan()
    w._on_rerun("order")
    assert calls == [], "a pipeline start must be refused while a dump is running"


def test_shell_dump_running_blocks_export_mp3(qtbot, tmp_path, monkeypatch):
    ws = str(tmp_path)
    _make_ds_playlist(ws)
    w = _mainwindow(qtbot, tmp_path, "ds")
    monkeypatch.setattr("deciwaves.gui.shell.config.load", lambda: {"ds_install": r"C:\DS"})
    w.dump._running = True                  # a dump batch is live
    calls = []
    w.runner.start = lambda argv, cwd=None: calls.append(argv) or True
    w.library.export.export_mp3_requested.emit(128)
    assert calls == [], "export MP3 must be refused while a dump is running"


def test_shell_dump_disables_then_reenables_pipeline_and_strip(qtbot, tmp_path):
    w = _mainwindow(qtbot, tmp_path, "ds")
    w.dump._running = True
    w._sync_running()
    assert w.pipeline.controls._scan_btn.isEnabled() is False
    assert w.pipeline.strip.rerun_enabled() is False
    # DumpRunner clears is_running before emitting finished; simulate the same order.
    w.dump._running = False
    w._on_dump_finished(2, 0)
    assert w.pipeline.controls._scan_btn.isEnabled() is True
    assert w.pipeline.strip.rerun_enabled() is True


# --- async Catalog-copy worker ---------------------------------------------

def test_catalog_copy_worker_copies_file_and_signals(qtbot, tmp_path):
    ws = str(tmp_path)
    src = os.path.join(ws, "out", "catalog.csv")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write("line_id\na\n")

    signals = _CatalogCopySignals()
    results = []
    signals.finished.connect(lambda msg: results.append(msg))

    dest = os.path.join(ws, "exported.csv")
    worker = _CatalogCopyWorker("ds", ws, dest, signals)
    worker.run()

    assert len(results) == 1
    assert "catalog copied" in results[0]
    assert os.path.isfile(dest)
    assert open(dest, encoding="utf-8").read() == "line_id\na\n"


def test_catalog_copy_worker_missing_source_signals_error(qtbot, tmp_path):
    ws = str(tmp_path)
    signals = _CatalogCopySignals()
    results = []
    signals.finished.connect(lambda msg: results.append(msg))

    dest = os.path.join(ws, "x.csv")
    worker = _CatalogCopyWorker("fw", ws, dest, signals)
    worker.run()

    assert len(results) == 1
    assert "no catalog artifact" in results[0]
