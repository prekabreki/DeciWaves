"""DS2 render stage (``games.ds2.render``): story-manifest -> ordered MP3 reels.

Install-free mirror of ``tests/test_fw_render.py``: stubbed concat/silence (never
shells out to ffmpeg), real WAV stubs under ``--audio-root``, and the spine
ordering asserted on the ACTUAL concatenation order -- not just the exit code.
"""
import csv
import os
import wave as wave_mod

from deciwaves.engine import render as engine_render
from deciwaves.games.ds2 import render, story_match


def _row(line_id, gidx, quest, tier="1", speaker="Sam", subtitle="x", wav=None):
    return {"line_id": line_id, "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "speaker": speaker, "subtitle": subtitle,
            "wav": wav or f"audio/{line_id}.wav"}


def _write_manifest(path, rows):
    cols = ["line_id", "gamescript_index", "quest", "tier", "speaker", "subtitle", "wav"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave_mod.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 4800)


def _render_argv(tmp_path, manifest, **extra):
    argv = ["--manifest", str(manifest),
            "--audio-root", str(tmp_path),
            "--out-dir", str(tmp_path / "reels"),
            "--cache", str(tmp_path / "cache"),
            "--errors", str(tmp_path / "render-errors.log")]
    for k, v in extra.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return argv


def _stub_concat_silence(monkeypatch):
    """Intercept the engine defaults DS2 render uses (it has no --uniform-mono
    fast path): concat writes a fake MP3 and records each wav_list; silence is
    a marker file that the ordering assertions filter out."""
    calls = []

    def fake_concat(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        calls.append(list(wav_list))
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")

    monkeypatch.setattr(engine_render, "_ffmpeg_concat", fake_concat)
    monkeypatch.setattr(engine_render, "silence_wav",
                        lambda secs, cache_dir: f"silence_{secs}.wav")
    return calls


def _clip_names(wav_list):
    return [os.path.basename(w) for w in wav_list
            if not os.path.basename(w).startswith("silence_")]


# ---------------------------------------------------------------------------
# CLI defaults: render's --manifest must be the file story_match actually
# writes by default, and the tier default must be exactly what match ships
# (strong 1 + accepted 2 -- DS2 has no subtitle-only tier-S, #370).
# ---------------------------------------------------------------------------

def test_render_default_manifest_matches_match_stage_output(parsed_stage_args):
    render_ns = parsed_stage_args(render.main, [])
    # story_match's --gamescript is required; only its defaults are under test.
    match_ns = parsed_stage_args(story_match.main, ["--gamescript", "dummy"])
    assert render_ns.manifest == match_ns.out


def test_render_default_tiers_ship_strong_and_accepted_binds(parsed_stage_args):
    ns = parsed_stage_args(render.main, [])
    tiers = {t.strip() for t in ns.tiers.split(",") if t.strip()}
    assert tiers == {"1", "2"}


# ---------------------------------------------------------------------------
# Ordering is the deliverable: the actual concatenation order must be
# gamescript order (sorted by gamescript_index, each quest a dense episode).
# ---------------------------------------------------------------------------

def test_reels_packed_in_gamescript_order(tmp_path, monkeypatch):
    for lid in ("c0", "c1", "c2", "c3"):
        _write_wav(tmp_path / "audio" / f"{lid}.wav")
    manifest = tmp_path / "story-manifest.csv"
    # deliberately out of order, interleaving two quests
    _write_manifest(manifest, [
        _row("c2", 5, "Q2"), _row("c0", 1, "Q1"),
        _row("c1", 3, "Q1"), _row("c3", 7, "Q2"),
    ])
    calls = _stub_concat_silence(monkeypatch)

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    assert _clip_names(calls[0]) == ["c0.wav", "c1.wav", "c2.wav", "c3.wav"]
    track = list((tmp_path / "reels").glob("ds2_story_reel_00.tracklist.csv"))
    assert len(track) == 1
    with open(track[0], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["line_id"] for r in rows] == ["c0", "c1", "c2", "c3"]


def test_out_of_tier_rows_dropped(tmp_path, monkeypatch):
    for lid in ("c0", "c1", "c2"):
        _write_wav(tmp_path / "audio" / f"{lid}.wav")
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [
        _row("c0", 1, "Q1", tier="1"),
        _row("c1", 2, "Q1", tier="2"),
        _row("c2", 3, "Q1", tier="3"),   # not in the default "1,2" -- dropped
    ])
    calls = _stub_concat_silence(monkeypatch)

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    assert _clip_names(calls[0]) == ["c0.wav", "c1.wav"]


# ---------------------------------------------------------------------------
# --single-file (deliverable 1): one MP3, story rows only (gamescript-bound =
# non-empty speaker), and a clear failure when nothing is story.
# ---------------------------------------------------------------------------

def test_single_file_writes_one_mp3_from_story_rows_only(tmp_path, monkeypatch):
    for lid in ("c0", "c1", "c2"):
        _write_wav(tmp_path / "audio" / f"{lid}.wav")
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [
        _row("c0", 1, "Q1", speaker="Sam"),
        _row("c1", 2, "Q1", speaker="", subtitle=""),   # filler: not story
        _row("c2", 3, "Q2", speaker="Tomo"),
    ])
    calls = _stub_concat_silence(monkeypatch)

    rc = render.main(_render_argv(tmp_path, manifest) + ["--single-file"])

    assert rc == 0
    assert _clip_names(calls[0]) == ["c0.wav", "c2.wav"]
    mp3s = list((tmp_path / "reels").glob("*.mp3"))
    assert len(mp3s) == 1
    assert mp3s[0].name == "ds2_story_reel.mp3"
    with open(tmp_path / "reels" / "ds2_story_reel.tracklist.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["line_id"] for r in rows] == ["c0", "c2"]


def test_single_file_zero_story_lines_fails_clearly(tmp_path, monkeypatch, capsys):
    for lid in ("c0", "c1"):
        _write_wav(tmp_path / "audio" / f"{lid}.wav")
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [
        _row("c0", 1, "Q1", speaker="", subtitle=""),
        _row("c1", 2, "Q1", speaker="", subtitle=""),
    ])
    _stub_concat_silence(monkeypatch)

    rc = render.main(_render_argv(tmp_path, manifest) + ["--single-file"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "story" in out
    assert not list((tmp_path / "reels").glob("*.mp3"))   # no 0-byte MP3


# ---------------------------------------------------------------------------
# main(): empty-state contract (issue #64) -- empty INPUT (header-only) is rc 1
# loud, an empty SELECTION (rows present, none in --tiers) is rc 0 no-op, and
# nothing decoded is rc 1 with a pointer to --errors.
# ---------------------------------------------------------------------------

def test_render_main_empty_input_manifest_is_upstream_error(tmp_path, capsys):
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [])   # header only, 0 data rows

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "no rows" in out
    assert str(manifest) in out
    assert "--tiers" not in out      # don't misdirect to a filter that can't help
    assert not (tmp_path / "cache").exists()


def test_render_main_empty_spine_is_a_noop_success(tmp_path, capsys):
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1", tier="3")])   # unbound tier

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to render" in out
    assert "--tiers" in out
    assert not (tmp_path / "render-errors.log").exists()   # measure never ran
    assert not (tmp_path / "cache").exists()               # assemble never ran


def test_render_main_missing_wavs_exits_nonzero_with_message(tmp_path, capsys):
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1"), _row("c1", 2, "Q1")])
    # no WAVs created under --audio-root: every measure fails

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc != 0
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert str(tmp_path / "render-errors.log") in out
    assert "--audio-root" in out
    assert "deciwaves ds2 extract" in out
    assert not list((tmp_path / "reels").glob("*.mp3"))


def test_render_main_missing_manifest_errors_cleanly(tmp_path, capsys):
    manifest = tmp_path / "story-manifest.csv"   # never written

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 1
    captured = capsys.readouterr()
    assert str(manifest) in captured.out          # names the missing file
    assert "deciwaves ds2 match" in captured.out  # the stage to run
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# msg_zero_story with tier R (issue #388)
# ---------------------------------------------------------------------------

def test_tier_R_only_single_file_zero_story_rc1_clear_message(tmp_path, monkeypatch, capsys):
    """--tiers R --single-file over an all-unmatched manifest: returns rc 1,
    names the real cause (region-ordered, gamescript-unmatched, tier R), and
    writes no MP3."""
    for lid in ("c0", "c1"):
        _write_wav(tmp_path / "audio" / f"{lid}.wav")
    manifest = tmp_path / "story-manifest.csv"
    _write_manifest(manifest, [
        _row("c0", 1, "Q1", tier="R", speaker="", subtitle="a"),
        _row("c1", 2, "Q1", tier="R", speaker="", subtitle="b"),
    ])
    _stub_concat_silence(monkeypatch)

    rc = render.main(_render_argv(tmp_path, manifest, tiers="R") + ["--single-file"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "tier R" in out
    assert "region-ordered" in out.lower() or "region" in out.lower()
    assert not list((tmp_path / "reels").glob("*.mp3"))
