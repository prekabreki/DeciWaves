"""Thin Qt preview player (#71, spec §6.5): play the WAV a :class:`PreviewResolver` resolves,
one line at a time, off the UI thread.

All decode logic lives in the Qt-free :mod:`deciwaves.gui.preview_model`; this widget only
adds the Qt glue -- a ``QThreadPool`` so a first-time DS/HZD decode (a subprocess) never
blocks the UI, a single audio sink so only one clip plays at a time, a generation token
so a slow decode whose result arrives after the user clicked a newer line is dropped instead
of playing over the top, and a cooperative cancel flag so a superseded in-flight
``_ResolveWorker`` (incl. an expensive DS ``PackIndex`` build) can bail early.

The actual ``play``/``stop`` sit behind an injectable *sink* (default: a lazily-built
``QSoundEffect``, the right primitive for a local WAV) so widget tests can substitute a fake
and assert playback without a real audio device -- CI has none.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal, Slot

from deciwaves.gui.preview_model import PreviewError


class _SoundEffectSink:
    """Default sink: one ``QSoundEffect`` playing local WAV, built lazily so no audio object
    is constructed until something actually plays (widget tests inject a fake instead)."""

    def __init__(self):
        self._effect = None

    def _ensure(self):
        if self._effect is None:
            from PySide6.QtMultimedia import QSoundEffect
            self._effect = QSoundEffect()
        return self._effect

    def play(self, path: str) -> None:
        effect = self._ensure()
        effect.stop()
        effect.setSource(QUrl.fromLocalFile(path))
        effect.play()

    def stop(self) -> None:
        if self._effect is not None:
            self._effect.stop()


class _WorkerSignals(QObject):
    """A ``QRunnable`` can't own signals, so it emits through this main-thread holder.
    Each payload carries the request's generation so the player can drop stale results."""

    done = Signal(int, str)      # generation, wav_path
    failed = Signal(int, str)    # generation, message


class _ResolveWorker(QRunnable):
    """Runs ``resolver.resolve_wav`` on a pool thread and reports the result (or a friendly
    error) back through the shared :class:`_WorkerSignals`.  Checks a cooperative cancel
    :class:`~threading.Event` before starting work so a superseded request (the user clicked
    a different line while this one was queued) skips its expensive decode."""

    def __init__(self, resolver, line_id, audio_path, generation, signals, cancel):
        super().__init__()
        self._resolver = resolver
        self._line_id = line_id
        self._audio_path = audio_path
        self._generation = generation
        self._signals = signals
        self._cancel = cancel

    def run(self) -> None:
        if self._cancel.is_set():
            return
        try:
            path = self._resolver.resolve_wav(self._line_id, self._audio_path)
        except PreviewError as exc:
            self._signals.failed.emit(self._generation, str(exc))
            return
        except Exception as exc:  # backstop: an unexpected decode error must not crash the pool
            self._signals.failed.emit(self._generation, f"Preview failed: {exc}")
            return
        if self._cancel.is_set():
            return
        self._signals.done.emit(self._generation, path)


class PreviewPlayer(QObject):
    """Plays one preview line at a time. ``play_line`` supersedes any in-flight request, so a
    rapid click sequence only ever plays the last line the user asked for."""

    preview_failed = Signal(str)   # friendly message -> shell surfaces it in the log console
    now_playing = Signal(str)      # wav path that just started playing

    def __init__(self, parent=None, sink=None, pool=None):
        super().__init__(parent)
        self._sink = sink if sink is not None else _SoundEffectSink()
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._signals = _WorkerSignals()
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._generation = 0
        self._cancel = threading.Event()

    def play_line(self, resolver, line_id: str, audio_path: str | None) -> None:
        """Resolve *line_id* off the UI thread and play it, stopping any current playback and
        superseding any in-flight decode (its result will be ignored when it arrives, and the
        previous in-flight worker is cooperatively cancelled so it does not run to completion
        on a superseded request)."""
        self._cancel.set()
        self._generation += 1
        self._sink.stop()
        self._cancel.clear()
        worker = _ResolveWorker(resolver, line_id, audio_path, self._generation, self._signals, self._cancel)
        self._pool.start(worker)

    def stop(self) -> None:
        self._sink.stop()

    @Slot(int, str)
    def _on_done(self, generation: int, path: str) -> None:
        if generation != self._generation:
            return  # a newer request superseded this one -- drop the stale result
        self._sink.play(path)
        self.now_playing.emit(path)

    @Slot(int, str)
    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return  # stale failure from a superseded request
        self.preview_failed.emit(message)
