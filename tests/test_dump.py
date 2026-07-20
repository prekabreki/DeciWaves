"""CLI dump stage: decode selected line ids to WAV for all three games."""
import csv
import os
import wave

import pytest

from deciwaves.games.ds import dump as ds_dump
from deciwaves.games.hzd import dump as hzd_dump
from deciwaves.games.fw import dump as fw_dump


def _write_wav(path, duration_secs=0.5, sr=48000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        n = int(duration_secs * sr)
        w.writeframes(b"\x00\x00" * n)


def test_fw_dump_ten_ids_produce_ten_wavs(tmp_path):
    ids = [f"line_{i:04d}" for i in range(10)]
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("\n".join(ids) + "\n")

    audio_dir = tmp_path / "audio"
    for lid in ids:
        _write_wav(os.path.join(audio_dir, f"{lid}.wav"))
    manifest = tmp_path / "clip-index.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
        for lid in ids:
            w.writerow({"line_id": lid, "wav": f"audio/{lid}.wav"})

    out_dir = tmp_path / "out"
    rc = fw_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--audio-dir", str(audio_dir),
        "--manifest", str(manifest),
    ])

    assert rc == 0
    found = sorted(os.listdir(out_dir))
    assert len(found) == 10
    for i, lid in enumerate(ids):
        # _safe_name transforms line_id: no special chars here, so name is the line_id
        assert f"{lid}.wav" in found


def test_fw_dump_unknown_ids_reported(tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("known_001\nunknown_999\nknown_002\nnobody_here\n")

    audio_dir = tmp_path / "audio"
    _write_wav(os.path.join(audio_dir, "known_001.wav"))
    _write_wav(os.path.join(audio_dir, "known_002.wav"))
    manifest = tmp_path / "clip-index.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
        w.writerow({"line_id": "known_001", "wav": "audio/known_001.wav"})
        w.writerow({"line_id": "known_002", "wav": "audio/known_002.wav"})

    out_dir = tmp_path / "out"
    rc = fw_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--audio-dir", str(audio_dir),
        "--manifest", str(manifest),
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "WARNING - unknown" in captured.out
    assert "WARNING - unknown line_id: unknown_999" in captured.out
    assert "WARNING - unknown line_id: nobody_here" in captured.out
    assert os.path.isfile(os.path.join(out_dir, "known_001.wav"))
    assert os.path.isfile(os.path.join(out_dir, "known_002.wav"))


def test_fw_dump_empty_ids_file(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("")
    out_dir = tmp_path / "out"
    rc = fw_dump.main(["--ids", str(ids_file), "--out", str(out_dir)])
    assert rc == 0
    # out dir is never created (early return before os.makedirs)
    assert not os.path.isdir(out_dir)


def test_fw_dump_duplicate_ids(tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("dup_001\ndup_001\n")
    audio_dir = tmp_path / "audio"
    _write_wav(os.path.join(audio_dir, "dup_001.wav"))
    manifest = tmp_path / "clip-index.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
        w.writerow({"line_id": "dup_001", "wav": "audio/dup_001.wav"})

    out_dir = tmp_path / "out"
    rc = fw_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--audio-dir", str(audio_dir),
        "--manifest", str(manifest),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "2 ok" in captured.out
    # Both copies succeed; second one gets a dedup suffix.
    files = sorted(os.listdir(out_dir))
    assert "dup_001.wav" in files
    assert "dup_001_1.wav" in files


def test_hzd_pre_bind_manifest_missing(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("line_001\n")
    out_dir = tmp_path / "out"
    manifest = tmp_path / "asr-manifest.csv"
    # manifest does NOT exist
    rc = hzd_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--manifest", str(manifest),
        "--clip-index", str(tmp_path / "nope.csv"),
    ])
    assert rc == 1


def test_hzd_pre_bind_manifest_empty(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("line_001\n")
    manifest = tmp_path / "asr-manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "clip_row", "tier"])
        w.writeheader()
    clip_index = tmp_path / "clip-index.csv"
    with open(clip_index, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["clip_row", "offset", "a_bytes"])
        w.writeheader()
    out_dir = tmp_path / "out"
    rc = hzd_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--manifest", str(manifest),
        "--clip-index", str(clip_index),
    ])
    assert rc == 1


def test_hzd_pre_bind_message(tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("line_001\n")
    out_dir = tmp_path / "out"
    manifest = tmp_path / "asr-manifest.csv"
    rc = hzd_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--manifest", str(manifest),
        "--clip-index", str(tmp_path / "nope.csv"),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "bind" in captured.out.lower()


def test_hzd_dump_missing_package(tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("line_001\n")
    manifest = tmp_path / "asr-manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "clip_row", "tier"])
        w.writeheader()
        w.writerow({"line_id": "line_001", "clip_row": "1", "tier": "S"})
    clip_index = tmp_path / "clip-index.csv"
    with open(clip_index, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["clip_row", "offset", "a_bytes"])
        w.writeheader()
        w.writerow({"clip_row": "1", "offset": "0", "a_bytes": "100"})
    out_dir = tmp_path / "out"
    bad_pkg = tmp_path / "not-a-package"
    rc = hzd_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--package", str(bad_pkg),
        "--manifest", str(manifest),
        "--clip-index", str(clip_index),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "package" in captured.out.lower()


def test_ds_dump_missing_data_dir(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("line_001\n")
    out_dir = tmp_path / "out"
    catalog = tmp_path / "catalog.csv"
    with open(catalog, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wem_path_en"])
        w.writeheader()
        w.writerow({"line_id": "line_001", "wem_path_en": "loc/x.wem.english"})
    rc = ds_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--data-dir", str(tmp_path / "no-data"),
        "--oodle", str(tmp_path / "no-oodle.dll"),
        "--catalog", str(catalog),
    ])
    assert rc == 1


def test_ds_dump_unknown_ids_reported(tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("known_001\nunknown_999\n")
    catalog = tmp_path / "catalog.csv"
    with open(catalog, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wem_path_en"])
        w.writeheader()
        w.writerow({"line_id": "known_001", "wem_path_en": "loc/x.wem.english"})
    # Create empty (but existing) data dir + dummy oodle so the stage
    # proceeds past install checks and reaches the per-id catalog lookup.
    data_dir = tmp_path / "empty-data"
    data_dir.mkdir()
    oodle = tmp_path / "dummy_oo2core.dll"
    oodle.write_text("")
    out_dir = tmp_path / "out"
    rc = ds_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--data-dir", str(data_dir),
        "--oodle", str(oodle),
        "--catalog", str(catalog),
    ])
    assert rc == 1  # known_001 decode fails (empty data dir); unknown is reported
    captured = capsys.readouterr()
    assert "WARNING - unknown line_id: unknown_999" in captured.out


def test_dump_helps_are_registered():
    from deciwaves.cli.main import STAGES
    for game in ("ds", "hzd", "fw"):
        assert "dump" in STAGES[game], f"dump missing from {game} stages"


def test_fw_dump_all_unknown_returns_nonzero(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("nobody_here\n")
    audio_dir = tmp_path / "audio"
    manifest = tmp_path / "clip-index.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
    out_dir = tmp_path / "out"
    rc = fw_dump.main([
        "--ids", str(ids_file),
        "--out", str(out_dir),
        "--audio-dir", str(audio_dir),
        "--manifest", str(manifest),
    ])
    assert rc == 1


def test_safe_name_basic():
    assert fw_dump._safe_name("MQ01_aloy_hello") == "MQ01_aloy_hello"


def test_safe_name_special_chars():
    assert fw_dump._safe_name("path/to/id") == "path_to_id"
    assert fw_dump._safe_name("id with spaces") == "id_with_spaces"


def test_safe_name_dedup():
    used = {"clip"}
    a = fw_dump._safe_name("clip", used)
    used.add(a)
    assert a == "clip_1"
    b = fw_dump._safe_name("clip", used)
    assert b == "clip_2"
