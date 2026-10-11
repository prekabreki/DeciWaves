import csv
import wave

import numpy as np
import pytest

from conftest import needs_ffmpeg
from deciwaves import data
from deciwaves.games.ds import keepspans_check as kc
from deciwaves.games.ds.speech_trim import MAX_SPANS, gate_spans, refuse_replacement

RATE = 48000


def _signal(seconds, bursts, level_db=-20.0):
    """Silence of `seconds` with a 440 Hz tone at `level_db` RMS over each (start, end)."""
    a = np.zeros(int(seconds * RATE))
    amp = 10 ** (level_db / 20) * np.sqrt(2)
    for start, end in bursts:
        i, j = int(start * RATE), int(end * RATE)
        a[i:j] = amp * np.sin(2 * np.pi * 440 * np.arange(j - i) / RATE)
    return a


def _approx(spans):
    return [(round(a, 2), round(b, 2)) for a, b in spans]


# --- gate_spans --------------------------------------------------------------

def test_gate_pads_a_loud_burst():
    spans, total = gate_spans(_signal(4.0, [(1.0, 2.0)]), RATE)
    assert total == 4.0
    assert _approx(spans) == [(0.65, 2.35)]


def test_gate_finds_nothing_in_silence_or_below_the_gate():
    assert gate_spans(np.zeros(RATE * 3), RATE)[0] == []
    assert gate_spans(_signal(3.0, [(0.5, 2.5)], level_db=-60.0), RATE)[0] == []


def test_gate_ignores_blips_shorter_than_min_keep():
    assert gate_spans(_signal(3.0, [(1.0, 1.1)]), RATE)[0] == []


def test_gate_merges_close_bursts_and_keeps_far_ones_apart():
    close, _ = gate_spans(_signal(6.0, [(1.0, 2.0), (2.6, 3.0)]), RATE)
    assert _approx(close) == [(0.65, 3.35)]
    far, _ = gate_spans(_signal(8.0, [(1.0, 2.0), (5.0, 6.0)]), RATE)
    assert _approx(far) == [(0.65, 2.35), (4.65, 6.35)]


def test_gate_clamps_to_track_bounds():
    spans, _ = gate_spans(_signal(2.0, [(0.0, 2.0)]), RATE)
    assert _approx(spans) == [(0.0, 2.0)]


# --- refuse_replacement ------------------------------------------------------

def test_guard_accepts_more_audio_within_the_span_limit():
    assert refuse_replacement([(1.0, 3.0)], []) is None
    assert refuse_replacement([(0.0, 5.0)], [(1.0, 2.0)]) is None


def test_guard_refuses_less_or_equal_audio():
    assert refuse_replacement([(1.0, 2.0)], [(0.0, 5.0)])
    assert refuse_replacement([(1.0, 2.0)], [(3.0, 4.0)])
    assert refuse_replacement([], [])


def test_guard_refuses_more_than_max_spans():
    seven = [(float(i), i + 0.5) for i in range(MAX_SPANS + 1)]
    assert refuse_replacement(seven, [])
    assert refuse_replacement(seven[:MAX_SPANS], []) is None


# --- check / emit over manifest rows -----------------------------------------

def _row(line_id, dropped, keep_spans="", ratio="0.0"):
    return {"stream_path": f"s/{line_id}", "line_id": line_id, "speech_ratio": ratio,
            "keep_spans": keep_spans, "dropped": dropped}


ROWS = [
    _row("healthy#track0", "0", "1.0:4.0", "0.5"),
    _row("missed#track0", "1"),
    _row("titlecard#track0", "1"),
    _row("silent#track0", "1"),
    _row("chopped#track0", "1"),
]
GATE = {
    "s/healthy#track0": ([(0.0, 9.0)], 10.0),
    "s/missed#track0": ([(2.0, 3.5)], 10.0),
    "s/titlecard#track0": ([(0.0, 1.0)], 80.0),
    "s/silent#track0": ([], 6.0),
    "s/chopped#track0": ([(float(i), i + 0.5) for i in range(MAX_SPANS + 1)], 20.0),
}


def _measure(calls):
    def fn(stream):
        calls.append(stream)
        return GATE[stream]
    return fn


def test_check_measures_only_dropped_rows():
    calls = []
    kc.check(ROWS, _measure(calls))
    assert "s/healthy#track0" not in calls
    assert len(calls) == 4


def test_check_flags_dropped_rows_with_audio_and_marks_reviewed():
    flagged, errors = kc.check(ROWS, _measure([]), reviewed={"titlecard#track0", "chopped#track0"})
    assert errors == []
    by_id = {f["line_id"]: f for f in flagged}
    assert set(by_id) == {"missed#track0", "titlecard#track0", "chopped#track0"}
    assert not by_id["missed#track0"]["reviewed"]
    assert by_id["titlecard#track0"]["reviewed"]
    assert by_id["missed#track0"]["kept"] == pytest.approx(1.5)


def test_check_reports_unmeasurable_tracks():
    def boom(stream):
        raise RuntimeError("decode failed")
    flagged, errors = kc.check([_row("x#track0", "1")], boom)
    assert flagged == []
    assert errors == [("x#track0", "decode failed")]


def test_emit_patches_only_the_named_dropped_row():
    patched, applied, refused = kc.emit(ROWS, ["missed#track0"], _measure([]))
    assert applied == ["missed#track0"] and refused == []
    new = {r["line_id"]: r for r in patched}
    assert new["missed#track0"]["keep_spans"] == "2.0:3.5"
    assert new["missed#track0"]["dropped"] == "0"
    assert new["missed#track0"]["speech_ratio"] == "0.15"
    for r_old, r_new in zip(ROWS, patched):
        if r_old["line_id"] != "missed#track0":
            assert r_new == r_old
    assert ROWS[1]["dropped"] == "1"           # input rows not mutated


def test_emit_refuses_healthy_rows_without_measuring_them():
    calls = []
    patched, applied, refused = kc.emit(ROWS, ["healthy#track0"], _measure(calls))
    assert applied == [] and calls == []
    assert refused[0][0] == "healthy#track0"
    assert patched == ROWS


def test_emit_refuses_fragmented_silent_and_unknown_rows():
    patched, applied, refused = kc.emit(
        ROWS, ["chopped#track0", "silent#track0", "nope#track0"], _measure([]))
    assert applied == []
    assert {n for n, _ in refused} == {"chopped#track0", "silent#track0", "nope#track0"}
    assert patched == ROWS


# --- packaged reviewed list --------------------------------------------------

def test_packaged_reviewed_list_names_only_dropped_rows_and_spares_the_real_misses():
    reviewed = kc.load_reviewed(data.packaged("ds/cutscene-keepspans-reviewed.csv"))
    with open(data.packaged("ds/cutscene-keepspans.csv"), newline="", encoding="utf-8-sig") as f:
        dropped = {r["line_id"] for r in csv.DictReader(f) if r["dropped"] == "1"}
    assert reviewed and set(reviewed) <= dropped
    assert all(reason.strip() for reason in reviewed.values())
    for miss in ("sq_cs10_s00700#track0", "sq_cs03_s01000#track0", "sq_cs71_s00920_c102#track0"):
        assert miss in dropped and miss not in reviewed


# --- WAV handling, as the stage decodes it -----------------------------------

def _write_wav(path, channels):
    """16-bit PCM WAV from a list of equal-length float channel arrays."""
    frames = np.stack(channels, axis=1)
    pcm = np.clip(np.round(frames * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def test_read_mono_averages_channels(tmp_path):
    p = tmp_path / "x.wav"
    _write_wav(p, [np.full(RATE, 0.5), np.zeros(RATE)])
    a, rate = kc.read_mono(str(p))
    assert rate == RATE and len(a) == RATE
    assert a.mean() == pytest.approx(0.25, abs=1e-4)


def _cutscene_wav(path, total, bursts):
    """6-channel track with dialogue only in the centre channel, like a DS cutscene."""
    centre = _signal(total, bursts)
    silent = np.zeros_like(centre)
    _write_wav(path, [silent, silent, centre, silent, silent, silent])


@needs_ffmpeg
def test_render_downmix_keeps_centre_channel_dialogue_above_the_gate(tmp_path):
    from deciwaves.engine.render import normalize_wav
    src = tmp_path / "track.wav"
    _cutscene_wav(src, 6.0, [(2.0, 3.0)])
    spans, total = gate_spans(*kc.read_mono(normalize_wav(str(src), str(tmp_path / "norm"))))
    assert total == pytest.approx(6.0, abs=0.01)
    assert _approx(spans) == [(1.65, 3.35)]


@needs_ffmpeg
def test_main_check_and_emit_end_to_end(tmp_path, monkeypatch, capsys):
    """main() wired to fixture tracks instead of an install: the check exits 1 on an
    unreviewed dropped track, 0 once it is reviewed, and --emit writes a guarded copy."""
    from deciwaves.engine import audio_clip
    from deciwaves.engine.pack import bin_index

    wavs = {"s/missed": (6.0, [(2.0, 3.0)]), "s/quiet": (6.0, [])}
    for stream, (total, bursts) in wavs.items():
        _cutscene_wav(tmp_path / f"{stream[2:]}.wav", total, bursts)
    monkeypatch.setattr(bin_index, "PackIndex", lambda data_dir, oodle: object())
    monkeypatch.setattr(audio_clip, "clip_wav",
                        lambda idx, stream, cache, vgmstream=None: (str(tmp_path / f"{stream[2:]}.wav"), 6.0))

    ks = tmp_path / "keepspans.csv"
    with open(ks, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["stream_path", "line_id", "speech_ratio", "keep_spans", "dropped"])
        w.writeheader()
        w.writerow({"stream_path": "s/missed", "line_id": "missed#track0", "speech_ratio": "0.0",
                    "keep_spans": "", "dropped": "1"})
        w.writerow({"stream_path": "s/quiet", "line_id": "quiet#track0", "speech_ratio": "0.0",
                    "keep_spans": "", "dropped": "1"})
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text("line_id,reason\n", encoding="utf-8")
    base = ["--data-dir", "d", "--oodle", "o", "--keepspans", str(ks), "--cache", str(tmp_path / "cache")]

    assert kc.main(base + ["--reviewed", str(reviewed)]) == 1
    assert "missed#track0" in capsys.readouterr().out

    reviewed.write_text("line_id,reason\nmissed#track0,heard it\n", encoding="utf-8")
    assert kc.main(base + ["--reviewed", str(reviewed)]) == 0

    out = tmp_path / "patched.csv"
    assert kc.main(base + ["--emit", "missed#track0", "--out", str(out)]) == 0
    with open(out, newline="", encoding="utf-8") as f:
        rows = {r["line_id"]: r for r in csv.DictReader(f)}
    assert rows["missed#track0"]["keep_spans"] == "1.65:3.35"
    assert rows["missed#track0"]["dropped"] == "0"
    assert rows["quiet#track0"]["dropped"] == "1"

    assert kc.main(base + ["--emit", "quiet#track0", "--out", str(out)]) == 1
