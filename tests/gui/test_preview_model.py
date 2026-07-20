"""Qt-free preview resolver (#71, spec §6.5). NO importorskip -- must pass on the base
``.[test]`` install (all decode imports are non-Qt). Covers the three per-game decode paths
(FW direct WAV, DS ``clip_wav``, HZD ``decode_wem_to_wav`` via the two CSV coord joins), the
heavy-handle caching (DS PackIndex built once, HZD cache-hit short-circuit), and every
friendly ``PreviewError`` case (unconfigured install/package, unknown line, missing file).
"""
import csv
import os

import pytest

from deciwaves.gui import preview_model
from deciwaves.gui.preview_model import PreviewError, PreviewResolver

HZD_MANIFEST = ["clip_row", "offset", "line_id", "speaker_name", "subtitle_en", "scene",
                "tier", "score", "transcript"]
HZD_CLIPIDX = ["clip_row", "offset", "a_bytes", "b_samples"]


def _write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_hzd_artifacts(ws):
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_MANIFEST,
               [{"clip_row": "5", "offset": "1000", "line_id": "h1", "speaker_name": "Aloy",
                 "subtitle_en": "Hi", "scene": "mq01", "tier": "S", "score": "9",
                 "transcript": "hi"}])
    _write_csv(os.path.join(ws, "out", "hzd", "clip-index.csv"), HZD_CLIPIDX,
               [{"clip_row": "5", "offset": "1000", "a_bytes": "2048", "b_samples": "48000"}])


# --- FW: no decode ---------------------------------------------------------

def test_fw_returns_existing_wav(tmp_path):
    wav = os.path.join(str(tmp_path), "out", "fw", "audio", "f1.wav")
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    with open(wav, "wb") as f:
        f.write(b"\x00" * 64)
    r = PreviewResolver("fw", str(tmp_path), cfg={})
    assert r.resolve_wav("f1", wav) == wav


def test_fw_missing_file_raises(tmp_path):
    r = PreviewResolver("fw", str(tmp_path), cfg={})
    with pytest.raises(PreviewError):
        r.resolve_wav("f2", os.path.join(str(tmp_path), "out", "fw", "audio", "missing.wav"))


def test_fw_no_audio_path_raises(tmp_path):
    r = PreviewResolver("fw", str(tmp_path), cfg={})
    with pytest.raises(PreviewError):
        r.resolve_wav("f3", None)


# --- DS: clip_wav, PackIndex built once ------------------------------------

def test_ds_decodes_with_stream_path_and_render_cache(tmp_path, monkeypatch):
    counts = {"n": 0}

    class _FakeIdx:
        def __init__(self, data_dir, oodle):
            counts["n"] += 1
            self.data_dir, self.oodle = data_dir, oodle

    seen = []

    def _fake_clip_wav(idx, stream_path, cache_dir, vgmstream=None):
        seen.append((idx, stream_path, cache_dir))
        out = os.path.join(cache_dir, "out.wav")
        os.makedirs(cache_dir, exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"\x00" * 64)
        return out, 1.0

    monkeypatch.setattr(preview_model, "PackIndex", _FakeIdx)
    monkeypatch.setattr(preview_model, "clip_wav", _fake_clip_wav)

    r = PreviewResolver("ds", str(tmp_path), cfg={"ds_install": r"C:\DS"})
    r.resolve_wav("d1", "voices/x.core.stream")
    r.resolve_wav("d2", "voices/y.core.stream")

    assert counts["n"] == 1  # PackIndex built once and reused
    assert [s[1] for s in seen] == ["voices/x.core.stream", "voices/y.core.stream"]
    assert seen[0][2] == os.path.join(str(tmp_path), "out", "wav-cache")
    assert isinstance(seen[0][0], _FakeIdx)
    assert seen[0][0].data_dir == os.path.join(r"C:\DS", "data")


def test_ds_uses_explicit_oodle_dll_when_configured(tmp_path, monkeypatch):
    class _FakeIdx:
        def __init__(self, data_dir, oodle):
            self.data_dir, self.oodle = data_dir, oodle

    captured = {}

    def _fake_clip_wav(idx, stream_path, cache_dir, vgmstream=None):
        captured["oodle"] = idx.oodle
        out = os.path.join(cache_dir, "o.wav")
        os.makedirs(cache_dir, exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"\x00" * 64)
        return out, 1.0

    monkeypatch.setattr(preview_model, "PackIndex", _FakeIdx)
    monkeypatch.setattr(preview_model, "clip_wav", _fake_clip_wav)
    r = PreviewResolver("ds", str(tmp_path), cfg={"ds_install": r"C:\DS", "oodle_dll": r"D:\oo.dll"})
    r.resolve_wav("d1", "voices/x.core.stream")
    assert captured["oodle"] == r"D:\oo.dll"


def test_ds_unconfigured_install_raises(tmp_path):
    r = PreviewResolver("ds", str(tmp_path), cfg={})
    with pytest.raises(PreviewError):
        r.resolve_wav("d1", "voices/x.core.stream")


def test_ds_no_stream_path_raises(tmp_path):
    r = PreviewResolver("ds", str(tmp_path), cfg={"ds_install": r"C:\DS"})
    with pytest.raises(PreviewError):
        r.resolve_wav("d1", None)


def test_ds_clip_error_becomes_preview_error(tmp_path, monkeypatch):
    class _FakeIdx:
        def __init__(self, data_dir, oodle):
            pass

    def _boom(idx, stream_path, cache_dir, vgmstream=None):
        raise RuntimeError("stream not in install")

    monkeypatch.setattr(preview_model, "PackIndex", _FakeIdx)
    monkeypatch.setattr(preview_model, "clip_wav", _boom)
    r = PreviewResolver("ds", str(tmp_path), cfg={"ds_install": r"C:\DS"})
    with pytest.raises(PreviewError):
        r.resolve_wav("d1", "voices/x.core.stream")


# --- HZD: two CSV coord joins -> decode ------------------------------------

def test_hzd_joins_coords_and_decodes(tmp_path, monkeypatch):
    ws = str(tmp_path)
    _write_hzd_artifacts(ws)

    class _FakeDsar:
        def read(self, offset, length):
            return f"wem:{offset}:{length}".encode()

    class _FakePkg:
        def __init__(self, package_dir):
            self.package_dir = package_dir

        def dsar_for(self, archive):
            return _FakeDsar()

    decoded = []

    def _fake_decode(wem_bytes, wav_path):
        decoded.append((wem_bytes, wav_path))
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)
        with open(wav_path, "wb") as f:
            f.write(b"\x00" * 64)

    monkeypatch.setattr(preview_model, "HzdPackage", _FakePkg)
    monkeypatch.setattr(preview_model, "decode_wem_to_wav", _fake_decode)

    r = PreviewResolver("hzd", ws, cfg={"hzd_package": "PKG"})
    wav = r.resolve_wav("h1", None)

    expected = os.path.join(ws, "out", "hzd", "wav-cache", "5.wav")
    assert wav == expected
    assert decoded == [(b"wem:1000:2048", expected)]


def test_hzd_cache_hit_skips_decode_and_package(tmp_path, monkeypatch):
    ws = str(tmp_path)
    _write_hzd_artifacts(ws)
    cached = os.path.join(ws, "out", "hzd", "wav-cache", "5.wav")
    os.makedirs(os.path.dirname(cached), exist_ok=True)
    with open(cached, "wb") as f:
        f.write(b"\x00" * 64)  # >44 bytes -> cache hit

    def _boom_pkg(*a, **k):
        raise AssertionError("HzdPackage must not be built on a cache hit")

    calls = []
    monkeypatch.setattr(preview_model, "HzdPackage", _boom_pkg)
    monkeypatch.setattr(preview_model, "decode_wem_to_wav", lambda *a: calls.append(a))

    r = PreviewResolver("hzd", ws, cfg={"hzd_package": "PKG"})
    assert r.resolve_wav("h1", None) == cached
    assert calls == []


def test_hzd_unknown_line_raises(tmp_path):
    ws = str(tmp_path)
    _write_hzd_artifacts(ws)
    r = PreviewResolver("hzd", ws, cfg={"hzd_package": "PKG"})
    with pytest.raises(PreviewError):
        r.resolve_wav("nope", None)


def test_hzd_unconfigured_package_raises(tmp_path):
    ws = str(tmp_path)
    _write_hzd_artifacts(ws)  # maps resolve, but no package configured -> friendly error
    r = PreviewResolver("hzd", ws, cfg={})
    with pytest.raises(PreviewError):
        r.resolve_wav("h1", None)


def test_hzd_missing_coords_raises(tmp_path, monkeypatch):
    ws = str(tmp_path)
    # manifest maps h1 -> clip_row 5, but the clip-index has no row 5
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_MANIFEST,
               [{"clip_row": "5", "offset": "1000", "line_id": "h1", "speaker_name": "Aloy",
                 "subtitle_en": "Hi", "scene": "mq01", "tier": "S", "score": "9",
                 "transcript": "hi"}])
    _write_csv(os.path.join(ws, "out", "hzd", "clip-index.csv"), HZD_CLIPIDX, [])
    r = PreviewResolver("hzd", ws, cfg={"hzd_package": "PKG"})
    with pytest.raises(PreviewError):
        r.resolve_wav("h1", None)


# --- thread safety ---------------------------------------------------------

def test_threaded_resolve_does_not_double_build(tmp_path, monkeypatch):
    """Two threads resolving different HZD line_ids on one shared PreviewResolver.
    The lock must ensure lazy caches are built exactly once (AC #2)."""
    import threading
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_MANIFEST,
               [{"clip_row": "5", "offset": "1000", "line_id": "h1", "speaker_name": "Aloy",
                 "subtitle_en": "Hi", "scene": "mq01", "tier": "S", "score": "9",
                 "transcript": "hi"},
                {"clip_row": "7", "offset": "2000", "line_id": "h2", "speaker_name": "Aloy",
                 "subtitle_en": "Bye", "scene": "mq01", "tier": "S", "score": "9",
                 "transcript": "bye"}])
    _write_csv(os.path.join(ws, "out", "hzd", "clip-index.csv"), HZD_CLIPIDX,
               [{"clip_row": "5", "offset": "1000", "a_bytes": "2048", "b_samples": "48000"},
                {"clip_row": "7", "offset": "2000", "a_bytes": "1024", "b_samples": "48000"}])

    state = {"construct_count": 0, "decode_args": []}
    state_lock = threading.Lock()

    class _CountingDsar:
        def read(self, offset, length):
            return f"wem:{offset}:{length}".encode()

    class _CountingPkg:
        def __init__(self, package_dir):
            with state_lock:
                state["construct_count"] += 1
            self.package_dir = package_dir

        def dsar_for(self, archive):
            return _CountingDsar()

    def _fake_decode(wem_bytes, wav_path):
        with state_lock:
            state["decode_args"].append((wem_bytes, wav_path))
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)
        with open(wav_path, "wb") as f:
            f.write(b"\x00" * 64)

    monkeypatch.setattr(preview_model, "HzdPackage", _CountingPkg)
    monkeypatch.setattr(preview_model, "decode_wem_to_wav", _fake_decode)

    r = PreviewResolver("hzd", ws, cfg={"hzd_package": "PKG"})
    results = []
    errors = []

    def resolve(lid):
        try:
            results.append(r.resolve_wav(lid, None))
        except Exception as exc:
            errors.append((lid, exc))

    t1 = threading.Thread(target=resolve, args=("h1",))
    t2 = threading.Thread(target=resolve, args=("h2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert state["construct_count"] == 1
    assert len(errors) == 0, f"resolve errors: {errors}"
    assert len(results) == 2
    assert results[0] != results[1]
    wem_set = {d[0] for d in state["decode_args"]}
    assert b"wem:1000:2048" in wem_set
    assert b"wem:2000:1024" in wem_set
