import csv
import os
import wave

import pytest

from deciwaves.engine import render as rs
from deciwaves.games.ds.story_order import Segment


# --- helpers (mirroring the existing render-test style; these files are new,
# the existing render test files are untouched) ---------------------------------


def _seg(is_side, line_id, scene="sq_cs00_s00100", category="cutscene", episode=0):
    return Segment(episode=episode, is_side=is_side, pos=0.0, section=0, scene=scene,
                   line_index=0, track_index=0, category=category, speaker="Sam",
                   subtitle="hi", stream_path=f"{line_id}.core.stream", line_id=line_id)


def _write_wav(path, nchannels, seconds, framerate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(nchannels)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nchannels * int(seconds * framerate))


def _columns():
    return rs.ReelColumns(
        header=["timestamp", "scene", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [rs.format_ts(t), s.scene, s.speaker, s.subtitle, s.line_id])


def _fake_concat(calls):
    def concat_fn(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        calls.append({"wav_list": list(wav_list), "out_mp3": out_mp3,
                      "kwargs": kwargs})
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")
    return concat_fn


# --- bitrate_for_single_file ----------------------------------------------------


def test_bitrate_for_single_file_picks_expected_kbps():
    # 100 s fits even at the top of the standard ladder
    assert rs.bitrate_for_single_file(100.0) == 320
    # just past what 128 kbps fits rolls down to the next standard step, 112
    too_big_for_128 = rs.budget_seconds(target_mb=285.0, kbps=128) + 1.0
    assert rs.bitrate_for_single_file(too_big_for_128, target_mb=285.0) == 112
    # far past the floor it keeps rolling down, always to a STANDARD bitrate
    huge = rs.budget_seconds(target_mb=285.0, kbps=48) + 1.0
    assert rs.bitrate_for_single_file(huge, target_mb=285.0) == 40


def test_bitrate_for_single_file_boundary_and_just_past():
    # The whole point of the feature is the size limit: test AT it and just
    # past it, in both directions, across the whole standard ladder.
    next_lower = {320: 256, 256: 224, 224: 192, 192: 160, 160: 128, 128: 112,
                  112: 96, 96: 80, 80: 64, 64: 56, 56: 48, 48: 40, 40: 32}
    for kbps, lower in next_lower.items():
        at_limit = rs.budget_seconds(target_mb=285.0, kbps=kbps)
        # exactly at the boundary still fits at `kbps`
        assert rs.bitrate_for_single_file(at_limit, target_mb=285.0) == kbps
        # just past it rolls down exactly one standard step
        assert rs.bitrate_for_single_file(at_limit + 1e-3, target_mb=285.0) == lower


def test_bitrate_for_single_file_floor_exceeded_raises():
    # The boundary itself fits at the floor...
    assert rs.bitrate_for_single_file(
        rs.budget_seconds(target_mb=285.0, kbps=rs.DEFAULT_FLOOR_KBPS),
        target_mb=285.0) == rs.DEFAULT_FLOOR_KBPS
    # ...but anything past it is an explicit, clear failure, not an oversized file
    too_long = rs.budget_seconds(target_mb=285.0, kbps=rs.DEFAULT_FLOOR_KBPS) + 1.0
    with pytest.raises(ValueError, match="does not fit"):
        rs.bitrate_for_single_file(too_long, target_mb=285.0)


def test_bitrate_for_single_file_negative_duration_raises():
    with pytest.raises(ValueError, match="negative"):
        rs.bitrate_for_single_file(-1.0)


def test_bitrate_for_single_file_consistent_with_budget_seconds():
    # Assert the inverse relationship against budget_seconds itself (not by
    # re-deriving the arithmetic): whatever bitrate is picked, the duration
    # must fit budget_seconds(...) at that bitrate.
    for total in (100.0, 5_000.0, 17_000.0, 30_000.0, 60_000.0):
        kbps = rs.bitrate_for_single_file(total, target_mb=285.0)
        assert total <= rs.budget_seconds(285.0, rs.MP3_OVERHEAD, kbps), (
            f"{total}s picked {kbps} kbps, which does not fit")
    # Non-vacuous: a pick one standard step too high would violate the property.
    total = rs.budget_seconds(285.0, rs.MP3_OVERHEAD, 128) + 1.0
    picked = rs.bitrate_for_single_file(total, target_mb=285.0)
    assert picked == 112
    assert total > rs.budget_seconds(285.0, rs.MP3_OVERHEAD, 128)  # 128 does NOT fit


def test_encoded_size_mb_is_budget_seconds_inverse():
    for kbps in (320, 128, 40):
        secs = rs.budget_seconds(target_mb=285.0, kbps=kbps)
        assert rs.encoded_size_mb(secs, kbps) == pytest.approx(285.0, rel=1e-9)


# --- assemble_single_file -------------------------------------------------------


def test_assemble_single_file_story_predicate_excludes_filler(tmp_path):
    segs = [
        _seg(0, "story_a", scene="s1", episode=0),
        _seg(1, "filler_b", scene="s1", episode=0),
        _seg(0, "story_c", scene="s2", episode=0),
    ]
    durations = {"story_a": ("wav_a", 1.0), "filler_b": ("wav_b", 1.0),
                 "story_c": ("wav_c", 1.0)}
    calls = []

    n = rs.assemble_single_file(
        segs, durations, story_predicate=lambda s: s.is_side == 0,
        out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"), stem="story",
        columns=_columns(), gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n == 1
    # filler excluded from the concat input; the two story clips keep their order
    clips = [w for w in calls[0]["wav_list"] if os.path.basename(w).startswith("wav_")]
    assert clips == ["wav_a", "wav_c"]
    # the gap between them is SCENE_GAP (scene changed), like assemble_reels
    assert "1500ms" in os.path.basename(calls[0]["wav_list"][1])
    # the tracklist has exactly the two story rows, no filler row
    rows = (tmp_path / "story.tracklist.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3
    assert rows[0] == "timestamp,scene,speaker,subtitle,line_id"
    assert rows[1].endswith("story_a")
    assert rows[2].endswith("story_c")


def test_assemble_single_file_prints_bitrate_and_size_before_concat(tmp_path, capsys):
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 100.0)}
    calls = []

    n = rs.assemble_single_file(
        segs, durations, story_predicate=lambda s: True,
        out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"), stem="story",
        columns=_columns(), gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n == 1
    out = capsys.readouterr().out
    assert "100.0s" in out
    assert "320 kbps" in out            # 100 s fits at the top of the ladder
    assert "MB" in out                  # predicted size is printed
    assert calls[0]["kwargs"]["kbps"] == 320  # the encode used the chosen bitrate


def test_assemble_single_file_no_story_returns_zero_and_writes_nothing(tmp_path):
    segs = [_seg(1, "filler", scene="s1", episode=0)]
    durations = {"filler": ("wav", 1.0)}
    calls = []

    n = rs.assemble_single_file(
        segs, durations, story_predicate=lambda s: s.is_side == 0,
        out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"), stem="story",
        columns=_columns(), gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n == 0
    assert calls == []                                   # never encoded
    assert not (tmp_path / "story.mp3").exists()         # no 0-byte MP3
    assert not (tmp_path / "story.tracklist.csv").exists()


def test_assemble_single_file_forces_chosen_kbps_over_caller(tmp_path):
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 50_000.0)}   # long enough to force a low bitrate
    calls = []

    rs.assemble_single_file(
        segs, durations, story_predicate=lambda s: True,
        out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"), stem="story",
        columns=_columns(), gap_key=lambda s: s.scene,
        concat_fn=_fake_concat(calls), concat_kwargs={"kbps": 320})

    chosen = rs.bitrate_for_single_file(50_000.0, target_mb=285.0)
    assert calls[0]["kwargs"]["kbps"] == chosen
    assert calls[0]["kwargs"]["kbps"] != 320  # the caller's kbps did not win


def test_assemble_single_file_refuses_absolute_stem(tmp_path):
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 1.0)}
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(ValueError, match="stem"):
        rs.assemble_single_file(
            segs, durations, story_predicate=lambda s: True,
            out_dir=str(out_dir), cache_dir=str(tmp_path / "cache"),
            stem=str(out_dir / "story"), columns=_columns(),
            gap_key=lambda s: s.scene, concat_fn=_fake_concat([]))

    assert not (out_dir / "story.mp3").exists()


# --- per-game story predicates --------------------------------------------------


def test_ds_is_story_matches_main_story_only():
    from deciwaves.games.ds import render as ds_render
    segs = [_seg(0, "a"), _seg(1, "b"), _seg(0, "c")]
    kept = [s for s in segs if ds_render.is_story(s)]
    assert [s.line_id for s in kept] == ["a", "c"]
    assert kept == ds_render.main_story_only(segs)


def test_ds_is_story_culls_non_story_cutscene_groups():
    from deciwaves.games.ds import render as ds_render
    segs = [
        _seg(0, "story_cut", scene="sq_cs02_s00400", category="cutscene"),
        _seg(0, "battlefield", scene="sq_cs71_s00270_c101", category="cutscene"),
        _seg(0, "mission", scene="lines_m00030", category="mission"),
    ]
    kept = [s for s in segs
            if ds_render.is_story(s, non_story_cs_groups={"cs71"})]
    assert [s.line_id for s in kept] == ["story_cut", "mission"]


def test_fw_is_story_requires_gamescript_bound_speaker():
    from deciwaves.games.fw.render import RenderItem, is_story
    story = RenderItem(gamescript_index=1, episode=0, quest="Q1", speaker="Aloy",
                       subtitle="x", line_id="c0", wav="audio/c0.wav")
    filler = RenderItem(gamescript_index=2, episode=0, quest="Q1", speaker="",
                        subtitle="x", line_id="s1", wav="audio/s1.wav")
    assert is_story(story)
    assert not is_story(filler)


# --- DS CLI wiring --------------------------------------------------------------


def _ds_render_argv(tmp_path, playlist, extra=()):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return [
        "--data-dir", str(data_dir),
        "--oodle", str(tmp_path / "fake_oodle.dll"),
        "--playlist", str(playlist),
        "--out-dir", str(tmp_path / "out-audio"),
        "--cache", str(tmp_path / "cache"),
        "--errors", str(tmp_path / "render-errors.log"),
        *extra,
    ]


def _stub_ds_decode(monkeypatch, tmp_path):
    from deciwaves.engine import audio_clip as ac

    def fake_clip_wav(idx, stream_path, cache_dir, vgmstream=None):
        os.makedirs(cache_dir, exist_ok=True)
        wav = os.path.join(cache_dir, os.path.basename(stream_path) + ".wav")
        _write_wav(wav, 1, 1.0)
        return wav, 1.0

    monkeypatch.setattr(ac, "clip_wav", fake_clip_wav)

    def fake_concat(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")

    monkeypatch.setattr(rs, "_ffmpeg_concat", fake_concat)


def test_ds_render_main_single_file_story_only(tmp_path, monkeypatch, capsys):
    from deciwaves.games.ds import render as ds_render
    from deciwaves.games.ds.story_order import write_playlist

    playlist = tmp_path / "playlist.csv"
    write_playlist([
        _seg(0, "story1", scene="sq_cs00_s00100", episode=0),
        _seg(1, "filler", scene="lines_pr201", episode=0),
        _seg(0, "story2", scene="sq_cs01_s00100", episode=1),
    ], str(playlist))
    _stub_ds_decode(monkeypatch, tmp_path)

    rc = ds_render.main(_ds_render_argv(
        tmp_path, playlist, extra=["--min-silence", "0", "--single-file"]))

    assert rc == 0
    mp3 = tmp_path / "out-audio" / "phase_d_main.mp3"
    assert mp3.is_file()
    assert not (tmp_path / "out-audio" / "phase_d_main_00.mp3").exists()  # ONE file
    rows = (tmp_path / "out-audio" / "phase_d_main.tracklist.csv").read_text(
        encoding="utf-8").splitlines()
    assert rows[0] == "timestamp,episode,category,speaker,subtitle,line_id"
    assert any(r.endswith("story1") for r in rows)
    assert any(r.endswith("story2") for r in rows)
    assert not any("filler" in r for r in rows)
    out = capsys.readouterr().out
    assert "kbps" in out and "MB" in out   # chosen bitrate + predicted size printed


def test_ds_render_main_single_file_no_story_fails_clearly(tmp_path, monkeypatch, capsys):
    from deciwaves.engine import audio_clip as ac
    from deciwaves.games.ds import render as ds_render
    from deciwaves.games.ds.story_order import write_playlist

    playlist = tmp_path / "playlist.csv"
    write_playlist([_seg(1, "side1"), _seg(1, "side2")], str(playlist))
    # No clip_wav stub: with a story-only selection the filler is dropped
    # BEFORE decode, so decode must never even run.
    def no_decode(*a, **k):
        raise AssertionError("decode ran on an all-filler single-file selection")
    monkeypatch.setattr(ac, "clip_wav", no_decode)

    rc = ds_render.main(_ds_render_argv(
        tmp_path, playlist, extra=["--single-file"]))

    assert rc == 1
    out = capsys.readouterr().out
    assert "is story" in out
    assert not (tmp_path / "out-audio" / "phase_d_main.mp3").exists()


def test_ds_render_main_single_file_empty_input_returns_1(tmp_path, capsys):
    from deciwaves.games.ds import render as ds_render
    from deciwaves.games.ds.story_order import write_playlist

    playlist = tmp_path / "playlist.csv"
    write_playlist([], str(playlist))

    rc = ds_render.main(_ds_render_argv(tmp_path, playlist, extra=["--single-file"]))

    assert rc == 1
    assert "has no rows" in capsys.readouterr().out


# --- FW CLI wiring --------------------------------------------------------------


def _fw_manifest_row(line_id, gidx, quest, tier="1", speaker="Aloy", subtitle="x",
                     wav=None):
    return {"line_id": line_id, "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "speaker": speaker, "subtitle": subtitle,
            "wav": wav or f"audio/{line_id}.wav"}


def _write_fw_manifest(path, rows):
    cols = ["line_id", "gamescript_index", "quest", "tier", "speaker", "subtitle", "wav"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_fw_clips(tmp_path, line_ids):
    audio = tmp_path / "audio"
    audio.mkdir()
    for lid in line_ids:
        _write_wav(audio / f"{lid}.wav", 1, 1.0)


def test_fw_render_main_single_file_story_only(tmp_path, monkeypatch, capsys):
    from deciwaves.games.fw import render

    manifest = tmp_path / "full-reel-manifest.csv"
    _write_fw_manifest(manifest, [
        _fw_manifest_row("c0", 1, "Q1", tier="1", speaker="Aloy"),
        _fw_manifest_row("s1", 2, "Q1", tier="S", speaker=""),     # filler
        _fw_manifest_row("c1", 3, "Q1", tier="2", speaker="Erend"),
    ])
    _write_fw_clips(tmp_path, ["c0", "s1", "c1"])

    def fake_concat(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")
    monkeypatch.setattr(render, "_concat_uniform", fake_concat)

    rc = render.main(["--manifest", str(manifest), "--audio-root", str(tmp_path),
                      "--out-dir", str(tmp_path / "reels"),
                      "--cache", str(tmp_path / "cache"),
                      "--errors", str(tmp_path / "render-errors.log"),
                      "--single-file", "--uniform-mono"])

    assert rc == 0
    mp3 = tmp_path / "reels" / "fw_story_reel.mp3"
    assert mp3.is_file()
    assert not (tmp_path / "reels" / "fw_story_reel_00.mp3").exists()  # ONE file
    rows = (tmp_path / "reels" / "fw_story_reel.tracklist.csv").read_text(
        encoding="utf-8").splitlines()
    assert rows[0] == "timestamp,quest,speaker,subtitle,line_id"
    assert any(r.endswith("c0") for r in rows)
    assert any(r.endswith("c1") for r in rows)
    assert not any(r.endswith("s1") for r in rows)   # tier-S filler excluded
    out = capsys.readouterr().out
    assert "kbps" in out and "MB" in out


def test_fw_render_main_single_file_no_story_fails_clearly(tmp_path, capsys):
    from deciwaves.games.fw import render

    manifest = tmp_path / "full-reel-manifest.csv"
    _write_fw_manifest(manifest, [
        _fw_manifest_row("s1", 1, "Q1", tier="S", speaker=""),
        _fw_manifest_row("s2", 2, "Q1", tier="S", speaker=""),
    ])
    _write_fw_clips(tmp_path, ["s1", "s2"])

    rc = render.main(["--manifest", str(manifest), "--audio-root", str(tmp_path),
                      "--out-dir", str(tmp_path / "reels"),
                      "--cache", str(tmp_path / "cache"),
                      "--errors", str(tmp_path / "render-errors.log"),
                      "--single-file"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "is story" in out
    assert not (tmp_path / "reels" / "fw_story_reel.mp3").exists()
