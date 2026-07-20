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
    assert len(signals) >= 1
    assert signals[0].current == 3


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
