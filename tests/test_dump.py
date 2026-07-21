"""Dump stage tests for all three games.

Tests the shared boundary handling (empty ids, unknown ids, duplicate ids),
the HZD pre-bind guard, and the critical DS catalog.csv fallback fix that
appends .core.stream to wem_path_en.
"""
import csv
import os
import wave
from unittest.mock import MagicMock


# -- helpers ----------------------------------------------------------------

def _write_ids(path, *ids):
    with open(path, "w", encoding="utf-8") as f:
        for lid in ids:
            f.write(lid + "\n")


def _write_playlist_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "stream_path", "subtitle_en"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_catalog_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wem_path_en", "subtitle_en"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_fw_manifest(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav", "speaker"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fake_clip_wav_capturer(captured):
    """Return a fake clip_wav that records stream_path arguments and returns a
    valid WAV.  *captured* is a list that gets *stream_path* appended."""
    def fake(idx, stream_path, cache_dir, vgmstream=None):
        captured.append(stream_path)
        os.makedirs(cache_dir, exist_ok=True)
        wav_path = os.path.join(cache_dir, "f.wav")
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(b"\x00\x00" * 480)
        return wav_path, 0.01
    return fake


# -- DS dump tests ----------------------------------------------------------

def test_ds_dump_10_ids_produces_10_wavs(tmp_path, monkeypatch):
    """playlist.csv with stream_path column: 10 IDs → 10 WAVs."""
    ids_list = [f"id_{i:04d}" for i in range(10)]
    playlist_rows = [
        {"line_id": lid, "stream_path": f"path/to/{lid}.wem.english.core.stream",
         "subtitle_en": f"line {i}"}
        for i, lid in enumerate(ids_list)]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_playlist_csv(out_dir / "playlist.csv", playlist_rows)
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, *ids_list)

    monkeypatch.setattr("deciwaves.games.ds.dump.config.load",
                        lambda: {"ds_install": "/f"})
    monkeypatch.setattr("deciwaves.games.ds.dump.config.resolve_ds_install",
                        lambda c: ("/f/data", "/f/oo2core.dll"))
    monkeypatch.setattr("deciwaves.games.ds.dump.PackIndex", MagicMock)

    captured = []
    monkeypatch.setattr("deciwaves.games.ds.dump.clip_wav",
                        _fake_clip_wav_capturer(captured))

    from deciwaves.games.ds import dump as ds_dump
    rc = ds_dump.main(["--ids", str(ids_file),
                        "--catalog", str(out_dir / "playlist.csv"),
                        "--out", str(out_dir / "dump")])

    assert rc == 0
    dump_dir = out_dir / "dump"
    wavs = [f for f in os.listdir(dump_dir) if f.endswith(".wav")]
    assert len(wavs) == 10
    assert len(captured) == 10
    for lid in ids_list:
        assert os.path.isfile(dump_dir / f"{lid}.wav")


def test_ds_dump_catalog_csv_fallback_appends_core_stream(tmp_path, monkeypatch):
    """No playlist.csv -- falls back to catalog.csv; every stream_path passed
    to clip_wav must end with .core.stream."""
    catalog_dir = tmp_path / "out"
    catalog_dir.mkdir()
    _write_catalog_csv(
        catalog_dir / "catalog.csv",
        [{"line_id": "id1", "wem_path_en": "path/to/a.wem.english",
          "subtitle_en": "A"},
         {"line_id": "id2", "wem_path_en": "path/to/b.wem.english",
          "subtitle_en": "B"}])
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "id1", "id2")

    monkeypatch.setattr("deciwaves.games.ds.dump.config.load",
                        lambda: {"ds_install": "/f"})
    monkeypatch.setattr("deciwaves.games.ds.dump.config.resolve_ds_install",
                        lambda c: ("/f/data", "/f/oo2core.dll"))
    monkeypatch.setattr("deciwaves.games.ds.dump.PackIndex", MagicMock)

    captured = []
    monkeypatch.setattr("deciwaves.games.ds.dump.clip_wav",
                        _fake_clip_wav_capturer(captured))

    from deciwaves.games.ds import dump as ds_dump
    rc = ds_dump.main(["--ids", str(ids_file), "--out", str(tmp_path / "dump")])

    assert rc == 0
    assert len(captured) == 2
    for s in captured:
        assert s.endswith(".core.stream"), f"{s!r} lacks .core.stream"
    assert "path/to/a.wem.english.core.stream" in captured
    assert "path/to/b.wem.english.core.stream" in captured


def test_ds_dump_empty_ids(tmp_path, monkeypatch):
    """Empty ids file → exit 1, no decode attempted."""
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("")
    monkeypatch.setattr("deciwaves.games.ds.dump.config.load", lambda: {})
    monkeypatch.setattr("deciwaves.games.ds.dump.config.resolve_ds_install",
                        lambda c: ("/f/data", "/f/oo2core.dll"))

    from deciwaves.games.ds import dump as ds_dump
    rc = ds_dump.main(["--ids", str(ids_file), "--out", str(tmp_path / "dump")])
    assert rc == 1


def test_ds_dump_unknown_ids(tmp_path, monkeypatch):
    """IDs not in the catalog → reported as skipped warnings, not a crash."""
    catalog_dir = tmp_path / "out"
    catalog_dir.mkdir()
    _write_playlist_csv(
        catalog_dir / "playlist.csv",
        [{"line_id": "known_1", "stream_path": "p/k1.core.stream",
          "subtitle_en": "k1"}])
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "known_1", "unknown_x")

    monkeypatch.setattr("deciwaves.games.ds.dump.config.load",
                        lambda: {"ds_install": "/f"})
    monkeypatch.setattr("deciwaves.games.ds.dump.config.resolve_ds_install",
                        lambda c: ("/f/data", "/f/oo2core.dll"))
    monkeypatch.setattr("deciwaves.games.ds.dump.PackIndex", MagicMock)
    monkeypatch.setattr("deciwaves.games.ds.dump.clip_wav",
                        _fake_clip_wav_capturer([]))

    from deciwaves.games.ds import dump as ds_dump
    rc = ds_dump.main(["--ids", str(ids_file),
                        "--catalog", str(catalog_dir / "playlist.csv"),
                        "--out", str(tmp_path / "dump")])
    assert rc == 0  # no decode errors → 0


def test_ds_dump_duplicate_ids(tmp_path, monkeypatch):
    """Duplicate IDs in the file → each is decoded once (no crash)."""
    catalog_dir = tmp_path / "out"
    catalog_dir.mkdir()
    _write_playlist_csv(
        catalog_dir / "playlist.csv",
        [{"line_id": "dup_id", "stream_path": "p/dup.core.stream",
          "subtitle_en": "dup"}])
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "dup_id", "dup_id")

    monkeypatch.setattr("deciwaves.games.ds.dump.config.load",
                        lambda: {"ds_install": "/f"})
    monkeypatch.setattr("deciwaves.games.ds.dump.config.resolve_ds_install",
                        lambda c: ("/f/data", "/f/oo2core.dll"))
    monkeypatch.setattr("deciwaves.games.ds.dump.PackIndex", MagicMock)

    captured = []
    monkeypatch.setattr("deciwaves.games.ds.dump.clip_wav",
                        _fake_clip_wav_capturer(captured))

    from deciwaves.games.ds import dump as ds_dump
    rc = ds_dump.main(["--ids", str(ids_file),
                        "--catalog", str(catalog_dir / "playlist.csv"),
                        "--out", str(tmp_path / "dump")])
    assert rc == 0
    assert len(captured) == 2


# -- HZD dump tests --------------------------------------------------------

def test_hzd_dump_pre_bind_guard(tmp_path):
    """Missing bind artifacts → clear message + non-zero exit."""
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "id1")
    from deciwaves.games.hzd import dump as hzd_dump
    rc = hzd_dump.main(["--ids", str(ids_file),
                         "--manifest", str(tmp_path / "no_such_manifest.csv"),
                         "--clip-index", str(tmp_path / "no_such_index.csv"),
                         "--package", str(tmp_path),
                         "--out", str(tmp_path / "dump")])
    assert rc == 1


def test_hzd_dump_unknown_ids(tmp_path, monkeypatch):
    """IDs without manifest entries → reported as missing, not crash."""
    manifest_dir = tmp_path / "out" / "hzd"
    manifest_dir.mkdir(parents=True)

    with open(manifest_dir / "asr-manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "clip_row"])
        w.writeheader()
        w.writerow({"line_id": "known_1", "clip_row": "0"})
    with open(manifest_dir / "clip-index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["clip_row", "offset", "a_bytes"])
        w.writeheader()
        w.writerow({"clip_row": "0", "offset": "0", "a_bytes": "100"})

    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "known_1", "unknown_x")

    # Mock the HzdPackage + DsarArchive to return valid RIFF bytes so
    # decode_wem_to_wav is reachable; mock decode_wem_to_wav to do nothing.
    payload = b"WAVE" + b"\x00" * 16
    riff = b"RIFF" + __import__("struct").pack("<I", len(payload)) + payload
    mock_dsar = MagicMock()
    mock_dsar.read.return_value = riff
    mock_pkg = MagicMock()
    mock_pkg.dsar_for.return_value = mock_dsar

    monkeypatch.setattr("deciwaves.games.hzd.dump.HzdPackage", lambda d: mock_pkg)
    monkeypatch.setattr("deciwaves.games.hzd.dump.decode_wem_to_wav", lambda w, p: None)

    from deciwaves.games.hzd import dump as hzd_dump
    rc = hzd_dump.main(["--ids", str(ids_file),
                         "--manifest", str(manifest_dir / "asr-manifest.csv"),
                         "--clip-index", str(manifest_dir / "clip-index.csv"),
                         "--package", str(tmp_path),
                         "--out", str(tmp_path / "dump")])
    assert rc == 0


# -- FW dump tests ---------------------------------------------------------

def test_fw_dump_unknown_ids(tmp_path):
    """IDs not in manifest → reported as missing."""
    manifest_dir = tmp_path / "out" / "fw"
    manifest_dir.mkdir(parents=True)
    _write_fw_manifest(
        manifest_dir / "manifest.csv",
        [{"line_id": "known_1", "wav": "audio/known_1.wav", "speaker": "aloy"}])
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "known_1", "unknown_x")

    from deciwaves.games.fw import dump as fw_dump
    rc = fw_dump.main(["--ids", str(ids_file),
                        "--manifest", str(manifest_dir / "manifest.csv"),
                        "--audio-dir", str(manifest_dir),
                        "--out", str(tmp_path / "dump")])
    assert rc == 1  # missing WAV file for known_1 too


def test_fw_dump_copies_wavs(tmp_path):
    """Known ID with existing WAV → file copied."""
    manifest_dir = tmp_path / "out" / "fw"
    manifest_dir.mkdir(parents=True)
    audio_dir = manifest_dir / "audio"
    audio_dir.mkdir()

    src_wav = audio_dir / "known_1.wav"
    import wave
    with wave.open(str(src_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 480)

    _write_fw_manifest(
        manifest_dir / "manifest.csv",
        [{"line_id": "known_1", "wav": "audio/known_1.wav", "speaker": "aloy"}])
    ids_file = tmp_path / "ids.txt"
    _write_ids(ids_file, "known_1")

    from deciwaves.games.fw import dump as fw_dump
    out_dir = tmp_path / "dump"
    rc = fw_dump.main(["--ids", str(ids_file),
                        "--manifest", str(manifest_dir / "manifest.csv"),
                        "--audio-dir", str(manifest_dir),
                        "--out", str(out_dir)])
    assert rc == 0
    assert os.path.isfile(out_dir / "known_1.wav")
