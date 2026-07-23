"""Tests for the within-stage progress model (issue #97)."""
import csv
import json
import os

from deciwaves.gui.progress_model import (
    StageProgress,
    asr_transcript_progress,
    catalog_progress,
    csv_output_progress,
    probe_progress,
    wav_cache_progress,
)


def _out(ws, game):
    return os.path.join(ws, "out") if game == "ds" else os.path.join(ws, "out", game)


def _write_catalog_processed(ws, game, lines):
    d = _out(ws, game)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "catalog-processed.txt"), "w", encoding="utf-8") as f:
        f.writelines(f"core/{i}\n" for i in range(lines))


def _write_csv(ws, game, name, rows, cols=None):
    if cols is None:
        cols = ["id", "val"]
    d = _out(ws, game)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i in range(rows):
            w.writerow([str(i), f"x{i}"])


def _make_wavs(ws, game, count):
    d = os.path.join(_out(ws, game), "wav-cache")
    os.makedirs(d, exist_ok=True)
    for i in range(count):
        open(os.path.join(d, f"clip{i}.wav"), "w").close()


def _make_render_input(ws, game, rows, name=None):
    """Write a render-input CSV for denominator testing."""
    if name is None:
        name = {"ds": "playlist.csv", "hzd": "asr-manifest.csv",
                "fw": "full-reel-manifest.csv"}[game]
    _write_csv(ws, game, name, rows=rows, cols=["line_id", "val"])


def _make_render_selection(ws, game, rows):
    """Write the GUI render-selection CSV (used for denominator)."""
    d = os.path.join(ws, "out", game, "gui")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "render-selection.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["line_id", "val"])
        for i in range(rows):
            w.writerow([f"line{i}", f"x{i}"])


def _make_silence_wav(ws, game, ms=750):
    d = os.path.join(_out(ws, game), "wav-cache")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f"silence_{ms}ms.wav"), "w").close()


def _make_norm_wavs(ws, game, count):
    d = os.path.join(_out(ws, game), "wav-cache", "norm")
    os.makedirs(d, exist_ok=True)
    for i in range(count):
        open(os.path.join(d, f"clip{i}.wav"), "w").close()


def _make_reel_mp3s(ws, game, count):
    subdir = {"ds": "audio", "hzd": "audio", "fw": "reels"}[game]
    d = os.path.join(_out(ws, game), subdir)
    os.makedirs(d, exist_ok=True)
    for i in range(count):
        open(os.path.join(d, f"reel_{i:02d}.mp3"), "w").close()


def _write_coverage(ws, bind_data):
    d = _out(ws, "hzd")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump({"bind": bind_data}, f)


# --- StageProgress properties -----------------------------------------------

def test_stageprogress_total_known():
    sp = StageProgress(current=42, total=100)
    assert sp.pct == 42.0
    assert "42 / 100" in sp.label
    assert "42%" in sp.label


def test_stageprogress_total_none():
    sp = StageProgress(current=42)
    assert sp.pct is None
    assert sp.label == "42"


# --- catalog_progress -------------------------------------------------------

def test_catalog_progress_no_file_yields_zero(tmp_path):
    p = catalog_progress(str(tmp_path), "ds")
    assert p.current == 0
    assert p.total is None


def test_catalog_progress_counts_lines(tmp_path):
    _write_catalog_processed(str(tmp_path), "ds", 42)
    p = catalog_progress(str(tmp_path), "ds")
    assert p.current == 42


def test_catalog_progress_hzd_uses_out_hzd_dir(tmp_path):
    _write_catalog_processed(str(tmp_path), "hzd", 7)
    p = catalog_progress(str(tmp_path), "hzd")
    assert p.current == 7


# --- asr_transcript_progress -----------------------------------------------

def test_asr_transcript_no_file_yields_zero(tmp_path):
    p = asr_transcript_progress(str(tmp_path))
    assert p.current == 0
    assert p.total is None


def test_asr_transcript_without_coverage_has_no_total(tmp_path):
    _write_csv(str(tmp_path), "hzd", "asr-transcripts.csv", rows=5)
    p = asr_transcript_progress(str(tmp_path))
    assert p.current == 5
    assert p.total is None


def test_asr_transcript_with_coverage_has_total(tmp_path):
    _write_csv(str(tmp_path), "hzd", "asr-transcripts.csv", rows=30)
    _write_coverage(str(tmp_path), {
        "clips_transcribed": 20, "clips_reused": 10, "clips_untranscribed": 70})
    p = asr_transcript_progress(str(tmp_path))
    assert p.total == 100
    assert p.pct == 30.0


def test_asr_transcript_zero_total_returns_none(tmp_path):
    _write_csv(str(tmp_path), "hzd", "asr-transcripts.csv", rows=5)
    _write_coverage(str(tmp_path), {
        "clips_transcribed": 0, "clips_reused": 0, "clips_untranscribed": 0})
    p = asr_transcript_progress(str(tmp_path))
    assert p.total is None


# --- wav_cache_progress ----------------------------------------------------

def test_wav_cache_progress(tmp_path):
    _make_wavs(str(tmp_path), "hzd", 7)
    open(os.path.join(_out(str(tmp_path), "hzd"), "wav-cache", "readme.txt"), "w").close()
    p = wav_cache_progress(str(tmp_path), "hzd")
    assert p.current == 7
    assert p.total is None


def test_wav_cache_empty_dir(tmp_path):
    os.makedirs(os.path.join(_out(str(tmp_path), "ds"), "wav-cache"), exist_ok=True)
    p = wav_cache_progress(str(tmp_path), "ds")
    assert p.current == 0


def test_wav_cache_missing_dir(tmp_path):
    p = wav_cache_progress(str(tmp_path), "ds")
    assert p.current == 0


# --- csv_output_progress ---------------------------------------------------

def test_csv_output_progress(tmp_path):
    _write_csv(str(tmp_path), "hzd", "asr-manifest.csv", rows=123)
    p = csv_output_progress(str(tmp_path), "hzd", "asr-manifest.csv")
    assert p.current == 123
    assert p.total is None


def test_csv_output_missing(tmp_path):
    p = csv_output_progress(str(tmp_path), "ds", "playlist.csv")
    assert p.current == 0


# --- probe_progress --------------------------------------------------------

def test_probe_catalog_stage(tmp_path):
    _write_catalog_processed(str(tmp_path), "ds", 5)
    signals = probe_progress(str(tmp_path), "ds", "catalog")
    assert len(signals) >= 1
    assert signals[0].current == 5


def test_probe_hzd_bind_stage(tmp_path):
    _write_csv(str(tmp_path), "hzd", "asr-transcripts.csv", rows=15)
    signals = probe_progress(str(tmp_path), "hzd", "bind")
    assert len(signals) >= 1


def test_probe_render_stage(tmp_path):
    _make_wavs(str(tmp_path), "ds", 3)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert len(signals) == 3
    assert signals[0].context == "decoding"
    assert signals[0].current == 3
    assert signals[1].context == "normalizing"
    assert signals[1].current == 0
    assert signals[2].context == "assembling reels"
    assert signals[2].current == 0


def test_probe_render_stage_total_none_when_no_input(tmp_path):
    _make_wavs(str(tmp_path), "ds", 5)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].total is None
    assert signals[1].total is None


def test_probe_render_decode_excludes_silence_wavs(tmp_path):
    _make_wavs(str(tmp_path), "ds", 5)
    _make_silence_wav(str(tmp_path), "ds", 750)
    _make_silence_wav(str(tmp_path), "ds", 3000)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].current == 5


def test_probe_render_decode_excludes_norm_subdir(tmp_path):
    _make_wavs(str(tmp_path), "ds", 4)
    _make_norm_wavs(str(tmp_path), "ds", 10)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].current == 4
    assert signals[1].current == 10


def test_probe_render_normalize_counts_norm_dir(tmp_path):
    _make_norm_wavs(str(tmp_path), "ds", 7)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[1].current == 7
    assert signals[1].context == "normalizing"


def test_probe_render_reels_counts_mp3s(tmp_path):
    _make_reel_mp3s(str(tmp_path), "ds", 3)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[2].current == 3
    assert signals[2].context == "assembling reels"


def test_probe_render_total_from_render_input(tmp_path):
    _make_wavs(str(tmp_path), "ds", 2)
    _make_render_input(str(tmp_path), "ds", 100)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].total == 100
    assert signals[1].total == 100


def test_probe_render_total_from_selection_preferred(tmp_path):
    _make_wavs(str(tmp_path), "ds", 2)
    _make_render_input(str(tmp_path), "ds", 200)
    _make_render_selection(str(tmp_path), "ds", 50)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].total == 50


def test_probe_render_total_not_zero(tmp_path):
    _make_render_input(str(tmp_path), "ds", 0)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].total is None


def test_probe_render_mid_render_state(tmp_path):
    _make_wavs(str(tmp_path), "ds", 100)
    _make_norm_wavs(str(tmp_path), "ds", 30)
    _make_reel_mp3s(str(tmp_path), "ds", 1)
    _make_render_input(str(tmp_path), "ds", 500)
    signals = probe_progress(str(tmp_path), "ds", "render")
    assert signals[0].current == 100
    assert signals[0].total == 500
    assert signals[1].current == 30
    assert signals[1].total == 500
    assert signals[2].current == 1
    assert signals[2].total is None


def test_probe_render_hzd_dirs(tmp_path):
    _make_wavs(str(tmp_path), "hzd", 10)
    _make_norm_wavs(str(tmp_path), "hzd", 3)
    _make_reel_mp3s(str(tmp_path), "hzd", 2)
    signals = probe_progress(str(tmp_path), "hzd", "render")
    assert signals[0].current == 10
    assert signals[1].current == 3
    assert signals[2].current == 2


def test_probe_render_fw_dirs(tmp_path):
    _make_wavs(str(tmp_path), "fw", 8)
    _make_norm_wavs(str(tmp_path), "fw", 2)
    _make_reel_mp3s(str(tmp_path), "fw", 1)
    signals = probe_progress(str(tmp_path), "fw", "render")
    assert signals[0].current == 8
    assert signals[1].current == 2
    assert signals[2].current == 1


def test_probe_render_wav_cache_progress_still_usable(tmp_path):
    p = wav_cache_progress(str(tmp_path), "ds")
    assert p.current == 0
    assert p.total is None
    assert p.context == "WAV cache"


def test_probe_unknown_stage_returns_empty(tmp_path):
    assert probe_progress(str(tmp_path), "ds", "nonexistent") == []


def test_probe_orders_csv(tmp_path):
    _write_csv(str(tmp_path), "ds", "playlist.csv", rows=20)
    signals = probe_progress(str(tmp_path), "ds", "order")
    csv_sigs = [s for s in signals if s.current == 20]
    assert csv_sigs


def test_probe_fw_asr_stage(tmp_path):
    _write_csv(str(tmp_path), "fw", "transcripts.csv", rows=99)
    signals = probe_progress(str(tmp_path), "fw", "asr")
    assert any(s.current == 99 for s in signals)
