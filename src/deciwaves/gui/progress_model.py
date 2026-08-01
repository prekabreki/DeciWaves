"""Qt-free within-stage progress model (issue #97).

Probes artifact growth to compute within-stage numeric progress where a
denominator is known.  Degrades gracefully to marker-level strip when not."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass

from deciwaves.gui.artifact_paths import out_dir, pipeline_render_input


@dataclass(frozen=True)
class StageProgress:
    current: int
    total: int | None = None
    context: str = ""

    @property
    def pct(self) -> float | None:
        if self.total is not None and self.total > 0:
            return self.current / self.total * 100.0
        return None

    @property
    def label(self) -> str:
        if self.total is not None:
            pct_str = f"({self.pct:.0f}%)"
            base = f"{self.current:,} / {self.total:,} {pct_str}"
        else:
            base = f"{self.current:,}"
        if self.context:
            return f"{self.context}: {base}"
        return base


def _line_count(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip())
    except OSError:
        return 0


def _csv_row_count(path: str) -> int:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for _ in reader)
    except (OSError, csv.Error):
        return 0


def _wav_count(dir_path: str) -> int:
    try:
        return sum(1 for fn in map(str.lower, os.listdir(dir_path)) if fn.endswith(".wav"))
    except OSError:
        return 0


def _file_count(dir_path: str, ext: str) -> int:
    try:
        ext_lower = ext.lower()
        return sum(1 for fn in map(str.lower, os.listdir(dir_path)) if fn.endswith(ext_lower))
    except OSError:
        return 0


def catalog_progress(workspace: str, game: str) -> StageProgress:
    path = os.path.join(out_dir(workspace, game), "catalog-processed.txt")
    return StageProgress(current=_line_count(path), context="catalog")


def asr_transcript_progress(workspace: str) -> StageProgress:
    n = _csv_row_count(os.path.join(workspace, "out", "hzd", "asr-transcripts.csv"))
    total: int | None = None
    cp = os.path.join(workspace, "out", "hzd", "coverage.json")
    try:
        with open(cp, encoding="utf-8") as f:
            cov = json.load(f)
        bind = cov.get("bind", {})
        if isinstance(bind, dict):
            transcribed = int(bind.get("clips_transcribed", 0))
            reused = int(bind.get("clips_reused", 0))
            untranscribed = int(bind.get("clips_untranscribed", 0))
            total = transcribed + reused + untranscribed
            if total == 0:
                total = None
    except (OSError, ValueError):
        pass
    return StageProgress(current=n, total=total, context="ASR transcript")


def wav_cache_progress(workspace: str, game: str) -> StageProgress:
    d = os.path.join(out_dir(workspace, game), "wav-cache")
    return StageProgress(current=_wav_count(d), context="WAV cache")


# ---------------------------------------------------------------------------
# Render sub-phase probes (issue #279)
# ---------------------------------------------------------------------------

def _render_out_dir(workspace: str, game: str) -> str:
    subdir = {"ds": "audio", "hzd": "audio", "fw": "reels"}.get(game, "audio")
    return os.path.join(out_dir(workspace, game), subdir)


def _render_cache_dir(workspace: str, game: str) -> str:
    return os.path.join(out_dir(workspace, game), "wav-cache")


def _decode_wav_count(workspace: str, game: str) -> int:
    d = _render_cache_dir(workspace, game)
    try:
        entries = os.listdir(d)
    except OSError:
        return 0
    return sum(
        1 for fn in map(str.lower, entries)
        if fn.endswith(".wav")
        and not (fn.startswith("silence_") and fn.endswith("ms.wav"))
    )


_CSV_ROW_COUNT_CACHE: dict[str, tuple[int | None, int | None, int]] = {}


def _cached_csv_row_count(path: str) -> int:
    """Row count for *path*, read at most once per ``(st_mtime_ns, st_size)`` identity.

    Issue #303: the render denominator CSV is written by the selection stage before the
    render starts and is never appended to during it, yet ``_render_total`` re-read it in
    full every 1.5 s poll. Cache on stat identity so an unchanged file is read once. The
    staleness ceiling is the next poll: any change to the file's size or mtime forces a
    re-read on the following poll, and a missed change (NTFS mtime ticks) can only serve
    a stale *total*, never a stale *current* count — which is why this is safe where an
    mtime-gated directory count is not.
    """
    try:
        st = os.stat(path)
        identity: tuple[int | None, int | None] = (st.st_mtime_ns, st.st_size)
    except OSError:
        identity = (None, None)
    cached = _CSV_ROW_COUNT_CACHE.get(path)
    if cached is not None and cached[:2] == identity:
        return cached[2]
    count = _csv_row_count(path)
    _CSV_ROW_COUNT_CACHE[path] = (identity[0], identity[1], count)
    return count


def _render_total(workspace: str, game: str) -> int | None:
    sel_path = os.path.join(workspace, "out", game, "gui", "render-selection.csv")
    count = _cached_csv_row_count(sel_path)
    if count > 0:
        return count
    source = pipeline_render_input(workspace, game)
    if source:
        count = _cached_csv_row_count(source)
        if count > 0:
            return count
    return None


def csv_output_progress(workspace: str, game: str, csv_name: str) -> StageProgress:
    path = os.path.join(out_dir(workspace, game), csv_name)
    return StageProgress(current=_csv_row_count(path), context=csv_name)


def probe_progress(workspace: str, game: str, stage: str) -> list[StageProgress]:
    signals: list[StageProgress] = []

    if stage == "catalog":
        signals.append(catalog_progress(workspace, game))

    if stage == "bind" and game == "hzd":
        signals.append(asr_transcript_progress(workspace))

    if stage == "render":
        total = _render_total(workspace, game)
        decode_dir = _render_cache_dir(workspace, game)
        norm_dir = os.path.join(decode_dir, "norm")
        signals.append(StageProgress(
            current=_decode_wav_count(workspace, game),
            total=total, context="decoding"))
        signals.append(StageProgress(
            current=_wav_count(norm_dir),
            total=total, context="normalizing"))
        signals.append(StageProgress(
            current=_file_count(_render_out_dir(workspace, game), ".mp3"),
            context="assembling reels"))

    output_csvs: dict[tuple[str, str], str] = {
        ("ds", "order"): "playlist.csv",
        ("hzd", "clip-index"): "clip-index.csv",
        ("hzd", "wem-metadata"): "wem-metadata.csv",
        ("hzd", "bind"): "asr-manifest.csv",
        ("fw", "extract"): "clip-index.csv",
        ("fw", "asr"): "transcripts.csv",
        ("fw", "subtitle-bind"): "subtitle-manifest-full.csv",
        ("fw", "full-reel"): "full-reel-manifest.csv",
    }
    csv_name = output_csvs.get((game, stage))
    if csv_name:
        signals.append(csv_output_progress(workspace, game, csv_name))

    return signals
