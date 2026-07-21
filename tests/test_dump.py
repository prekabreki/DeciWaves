"""Test the dump stage for all three games."""
import csv
import os

from deciwaves.games.ds import dump as ds_dump
from deciwaves.games.hzd import dump as hzd_dump
from deciwaves.games.fw import dump as fw_dump
from deciwaves.cli import config as cli_config


# ---- helpers ------------------------------------------------------------

def _write_ids(path, *ids):
    with open(path, "w", encoding="utf-8") as f:
        for lid in ids:
            f.write(lid + "\n")


def _write_min_wav(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * 64)


HZD_MANIFEST_COLS = ["clip_row", "offset", "line_id", "speaker_name",
                     "subtitle_en", "scene", "tier", "score", "transcript"]
HZD_CLIPIDX_COLS = ["clip_row", "offset", "a_bytes", "b_samples"]
FW_MANIFEST_COLS = ["line_id", "group_id", "lssr_index", "file_index",
                    "offset", "clip_bytes", "wav"]


def _write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---- DS dump ------------------------------------------------------------

class _FakePackIndex:
    def __init__(self, data_dir, oodle):
        self.data_dir = data_dir
        self.oodle = oodle


def _fake_clip_wav(idx, stream_path, cache_dir, vgmstream=None):
    out = os.path.join(cache_dir, "out.wav")
    os.makedirs(cache_dir, exist_ok=True)
    _write_min_wav(out)
    return out, 1.0


def test_ds_dump_10_ids_produces_10_wavs(tmp_path, monkeypatch):
    ws = str(tmp_path)
    catalog_path = os.path.join(ws, "out", "ds", "catalog.csv")
    _write_csv(catalog_path, ["line_id", "wem_path_en"],
               [{"line_id": f"id{i:03d}", "wem_path_en": f"stream{i}.wem"}
                for i in range(10)])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, *(f"id{i:03d}" for i in range(10)))
    out_dir = os.path.join(ws, "dump_out")

    monkeypatch.setattr(cli_config, "load", lambda: {"ds_install": r"C:\DS"})
    monkeypatch.setattr(cli_config, "resolve_ds_install",
                        lambda _: (r"C:\DS\data", r"C:\DS\oo2core_7_win64.dll"))
    monkeypatch.setattr(ds_dump, "PackIndex", _FakePackIndex)
    monkeypatch.setattr(ds_dump, "clip_wav", _fake_clip_wav)

    rc = ds_dump.main(["--ids", ids_path, "--out", out_dir, "--catalog", catalog_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 10


def test_ds_dump_unknown_ids_skipped(tmp_path, monkeypatch):
    ws = str(tmp_path)
    catalog_path = os.path.join(ws, "out", "ds", "catalog.csv")
    _write_csv(catalog_path, ["line_id", "wem_path_en"],
               [{"line_id": "known1", "wem_path_en": "s1.wem"}])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "known1", "unknown1", "unknown2")
    out_dir = os.path.join(ws, "dump_out")

    monkeypatch.setattr(cli_config, "load", lambda: {"ds_install": r"C:\DS"})
    monkeypatch.setattr(cli_config, "resolve_ds_install",
                        lambda _: (r"C:\DS\data", r"C:\DS\oo2core_7_win64.dll"))
    monkeypatch.setattr(ds_dump, "PackIndex", _FakePackIndex)
    monkeypatch.setattr(ds_dump, "clip_wav", _fake_clip_wav)

    rc = ds_dump.main(["--ids", ids_path, "--out", out_dir, "--catalog", catalog_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 1


def test_ds_dump_empty_ids_file(tmp_path, monkeypatch):
    ws = str(tmp_path)
    catalog_path = os.path.join(ws, "out", "ds", "catalog.csv")
    _write_csv(catalog_path, ["line_id", "wem_path_en"],
               [{"line_id": "id1", "wem_path_en": "s1.wem"}])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path)
    out_dir = os.path.join(ws, "dump_out")

    monkeypatch.setattr(cli_config, "load", lambda: {"ds_install": r"C:\DS"})
    monkeypatch.setattr(cli_config, "resolve_ds_install",
                        lambda _: (r"C:\DS\data", r"C:\DS\oo2core_7_win64.dll"))
    monkeypatch.setattr(ds_dump, "PackIndex", _FakePackIndex)
    monkeypatch.setattr(ds_dump, "clip_wav", _fake_clip_wav)

    rc = ds_dump.main(["--ids", ids_path, "--out", out_dir, "--catalog", catalog_path])
    assert rc == 0
    assert not os.path.isdir(out_dir) or not [f for f in os.listdir(out_dir) if f.endswith(".wav")]


# ---- HZD dump ----------------------------------------------------------

def test_hzd_dump_pre_bind_fails_nonzero(tmp_path):
    ws = str(tmp_path)
    # No asr-manifest.csv at all
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "id1")
    out_dir = os.path.join(ws, "dump_out")
    rc = hzd_dump.main(["--ids", ids_path, "--out", out_dir,
                         "--package", ws, "--manifest",
                         os.path.join(ws, "out", "hzd", "asr-manifest.csv")])
    assert rc != 0


def test_hzd_dump_pre_bind_empty_manifest_fails_nonzero(tmp_path):
    ws = str(tmp_path)
    manifest_path = os.path.join(ws, "out", "hzd", "asr-manifest.csv")
    _write_csv(manifest_path, HZD_MANIFEST_COLS, [])  # header only
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "id1")
    out_dir = os.path.join(ws, "dump_out")
    rc = hzd_dump.main(["--ids", ids_path, "--out", out_dir,
                         "--package", ws, "--manifest", manifest_path])
    assert rc != 0


def test_hzd_dump_10_ids_produces_10_wavs(tmp_path, monkeypatch):
    ws = str(tmp_path)
    # HzdPackage's hzd_package_error checks for PackFileLocators.bin
    _write_min_wav(os.path.join(ws, "PackFileLocators.bin"))
    manifest_path = os.path.join(ws, "out", "hzd", "asr-manifest.csv")
    clipidx_path = os.path.join(ws, "out", "hzd", "clip-index.csv")
    _write_csv(manifest_path, HZD_MANIFEST_COLS,
               [{"clip_row": str(i), "offset": str(i * 1000), "line_id": f"id{i:03d}",
                 "speaker_name": "Aloy", "subtitle_en": "", "scene": "mq01",
                 "tier": "S", "score": "9", "transcript": ""}
                for i in range(10)])
    _write_csv(clipidx_path, HZD_CLIPIDX_COLS,
               [{"clip_row": str(i), "offset": str(i * 1000), "a_bytes": "2048",
                 "b_samples": "48000"}
                for i in range(10)])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, *(f"id{i:03d}" for i in range(10)))
    out_dir = os.path.join(ws, "dump_out")

    class _FakeDsar:
        def read(self, offset, length):
            return b"RIFF\x00\x00\x00\x00WAVE"

    class _FakeHzdPkg:
        def __init__(self, pkg_dir):
            self.pkg_dir = pkg_dir

        def dsar_for(self, archive):
            return _FakeDsar()

    decoded = []

    def _fake_decode(wem_bytes, wav_path):
        decoded.append((wem_bytes, wav_path))
        _write_min_wav(wav_path)

    monkeypatch.setattr(hzd_dump, "HzdPackage", _FakeHzdPkg)
    monkeypatch.setattr(hzd_dump, "decode_wem_to_wav", _fake_decode)

    rc = hzd_dump.main(["--ids", ids_path, "--out", out_dir,
                         "--package", ws, "--manifest", manifest_path,
                         "--clip-index", clipidx_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 10
    assert len(decoded) == 10


def test_hzd_dump_unknown_ids_skipped(tmp_path, monkeypatch):
    ws = str(tmp_path)
    _write_min_wav(os.path.join(ws, "PackFileLocators.bin"))
    manifest_path = os.path.join(ws, "out", "hzd", "asr-manifest.csv")
    clipidx_path = os.path.join(ws, "out", "hzd", "clip-index.csv")
    _write_csv(manifest_path, HZD_MANIFEST_COLS,
               [{"clip_row": "0", "offset": "0", "line_id": "known1",
                 "speaker_name": "Aloy", "subtitle_en": "", "scene": "mq01",
                 "tier": "S", "score": "9", "transcript": ""}])
    _write_csv(clipidx_path, HZD_CLIPIDX_COLS,
               [{"clip_row": "0", "offset": "0", "a_bytes": "2048", "b_samples": "48000"}])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "known1", "unknown1")
    out_dir = os.path.join(ws, "dump_out")

    class _FakeDsar:
        def read(self, offset, length):
            return b"RIFF\x00\x00\x00\x00WAVE"

    class _FakeHzdPkg:
        def __init__(self, pkg_dir):
            self.pkg_dir = pkg_dir

        def dsar_for(self, archive):
            return _FakeDsar()

    monkeypatch.setattr(hzd_dump, "HzdPackage", _FakeHzdPkg)
    monkeypatch.setattr(hzd_dump, "decode_wem_to_wav",
                        lambda w, p: _write_min_wav(p))

    rc = hzd_dump.main(["--ids", ids_path, "--out", out_dir,
                         "--package", ws, "--manifest", manifest_path,
                         "--clip-index", clipidx_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 1


# ---- FW dump -----------------------------------------------------------

def test_fw_dump_10_ids_produces_10_wavs(tmp_path):
    ws = str(tmp_path)
    manifest_path = os.path.join(ws, "out", "fw", "clip-index.csv")
    rows = []
    for i in range(10):
        lid = f"id{i:03d}"
        wav_rel = f"audio/{lid}.wav"
        _write_min_wav(os.path.join(ws, "out", "fw", wav_rel))
        rows.append({"line_id": lid, "group_id": "0", "lssr_index": "0",
                     "file_index": "0", "offset": "0", "clip_bytes": "100",
                     "wav": wav_rel})
    _write_csv(manifest_path, FW_MANIFEST_COLS, rows)
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, *(f"id{i:03d}" for i in range(10)))
    out_dir = os.path.join(ws, "dump_out")

    rc = fw_dump.main(["--ids", ids_path, "--out", out_dir,
                        "--audio-root", os.path.join(ws, "out", "fw"),
                        "--manifest", manifest_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 10


def test_fw_dump_unknown_ids_skipped(tmp_path):
    ws = str(tmp_path)
    wav_rel = "audio/known1.wav"
    _write_min_wav(os.path.join(ws, "out", "fw", wav_rel))
    manifest_path = os.path.join(ws, "out", "fw", "clip-index.csv")
    _write_csv(manifest_path, FW_MANIFEST_COLS,
               [{"line_id": "known1", "group_id": "0", "lssr_index": "0",
                 "file_index": "0", "offset": "0", "clip_bytes": "100",
                 "wav": wav_rel}])
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "known1", "unknown1")
    out_dir = os.path.join(ws, "dump_out")

    rc = fw_dump.main(["--ids", ids_path, "--out", out_dir,
                        "--audio-root", os.path.join(ws, "out", "fw"),
                        "--manifest", manifest_path])
    assert rc == 0
    wavs = [f for f in os.listdir(out_dir) if f.endswith(".wav")]
    assert len(wavs) == 1


def test_fw_dump_no_manifest_fails(tmp_path):
    ws = str(tmp_path)
    ids_path = os.path.join(ws, "ids.txt")
    _write_ids(ids_path, "id1")
    out_dir = os.path.join(ws, "dump_out")
    rc = fw_dump.main(["--ids", ids_path, "--out", out_dir,
                        "--audio-root", os.path.join(ws, "out", "fw")])
    assert rc != 0
