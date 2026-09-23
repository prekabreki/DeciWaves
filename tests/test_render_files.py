"""``--files N`` (issue #415): pick the highest standard MP3 bitrate that packs
the render into at most N files of at most --target-mb each."""
import csv
import os
import wave

import pytest

from deciwaves.engine import render as rs
from deciwaves.games.ds import render as ds_render
from deciwaves.games.ds.story_order import Segment
from deciwaves.games.fw import render as fw_render

B = rs.budget_seconds   # seconds a 285 MB file holds at a bitrate, overhead included


def _seg(line_id, episode, scene):
    return Segment(episode=episode, is_side=0, pos=0.0, section=0, scene=scene,
                   line_index=0, track_index=0, category="cutscene", speaker="Sam",
                   subtitle="hi", stream_path=f"{line_id}.core.stream", line_id=line_id)


def _columns():
    return rs.ReelColumns(
        header=["timestamp", "scene", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [rs.format_ts(t), s.scene, s.speaker, s.subtitle, s.line_id])


def _fake_concat(calls):
    def concat_fn(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        calls.append({"wav_list": list(wav_list), "out_mp3": out_mp3, "kwargs": kwargs})
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")
    return concat_fn


# Mirrors the 2026-08-02 DS1 case: 3 files at 128 kbps, 2 at 112, 1 only at 64.
EPS_128_NEEDS_3 = [(0, 12_000.0), (1, 8_000.0), (2, 12_000.0)]


# --- plan_files -----------------------------------------------------------------


def test_fits_two_at_112_but_needs_three_at_128():
    assert len(rs.pack_episodes(EPS_128_NEEDS_3, budget=B(kbps=128))) == 3
    plan = rs.plan_files(EPS_128_NEEDS_3, 2)
    assert plan.kbps == 112
    assert plan.files == [[0, 1], [2]]
    assert plan.seconds == [20_000.0, 12_000.0]


def test_more_files_allow_a_higher_bitrate_and_one_file_the_lowest():
    assert rs.plan_files(EPS_128_NEEDS_3, 3).kbps == 160
    assert rs.plan_files(EPS_128_NEEDS_3, 1).kbps == 64


def test_predicted_count_accounts_for_mp3_overhead():
    """Each pair of episodes fits a 285 MB file at 128 kbps if MP3 framing
    overhead is ignored, but not once it is counted. Solving without the
    overhead divisor would promise 2 files at 128 and render 3."""
    ep = 8_850.0
    no_overhead = B(kbps=128, overhead=0.0)
    assert 2 * ep <= no_overhead and 2 * ep > B(kbps=128)
    eps = [(0, ep), (1, ep), (2, ep)]

    plan = rs.plan_files(eps, 2)

    assert plan.kbps == 112
    # the promise is what the real packer produces at the chosen bitrate
    rendered = rs.pack_episodes(eps, budget=B(kbps=plan.kbps))
    assert rendered == plan.files and len(rendered) == 2


def test_exact_multiple_of_the_budget_leaves_no_empty_trailing_file():
    budget = B(kbps=128)
    one = rs.plan_files([(0, budget / 2), (1, budget / 2)], 1)
    assert (one.kbps, one.files) == (128, [[0, 1]])
    two = rs.plan_files([(0, budget), (1, budget)], 2)
    assert (two.kbps, two.files) == (128, [[0], [1]])
    assert all(group for group in two.files)


def test_impossible_n_names_the_smallest_workable_n():
    eps = [(0, 50_000.0), (1, 50_000.0)]    # > 1 file even at 32 kbps
    with pytest.raises(rs.FilesDoNotFit, match="smallest file count that fits is 2") as ei:
        rs.plan_files(eps, 1)
    assert ei.value.smallest_n == 2
    # 48 kbps holds < 50,000 s per file, so 40 is the best bitrate for 2 files
    assert ei.value.smallest_kbps == 40 == rs.plan_files(eps, 2).kbps


def test_an_episode_too_long_for_any_file_fits_no_n():
    too_long = B(kbps=rs.DEFAULT_FLOOR_KBPS) + 1.0
    with pytest.raises(rs.FilesDoNotFit, match="nor in any number of files") as ei:
        rs.plan_files([(0, 10.0), (1, too_long)], 5)
    assert ei.value.smallest_n is None


def test_only_standard_bitrates_are_ever_chosen():
    for n in (1, 2, 3, 4):
        for total in (1_000.0, 20_000.0, 60_000.0):
            eps = [(i, total / 4) for i in range(4)]
            try:
                assert rs.plan_files(eps, n).kbps in rs.STANDARD_MP3_BITRATES
            except rs.FilesDoNotFit:
                pass


def test_file_seconds_counts_what_the_episode_totals_leave_out():
    """A group that fits on its episode totals alone but not once the gaps
    between its episodes are added must be rejected, or the file overflows."""
    budget = B(kbps=128)
    eps = [(0, budget / 2), (1, budget / 2)]
    plan = rs.plan_files(eps, 1, file_seconds=lambda group: budget / 2 * len(group) + 1.5)
    assert plan.kbps == 112


def test_rejects_zero_files():
    with pytest.raises(ValueError):
        rs.plan_files(EPS_128_NEEDS_3, 0)


def test_single_file_search_is_plan_files_with_one_file():
    for total in (100.0, 17_000.0, 18_000.0, 30_000.0, 60_000.0):
        assert (rs.bitrate_for_single_file(total)
                == rs.plan_files([(0, total)], 1).kbps)


# --- reel_seconds ---------------------------------------------------------------


def test_reel_seconds_matches_the_assembled_timeline(tmp_path):
    segs = [_seg("a", 0, "s1"), _seg("b", 0, "s1"), _seg("c", 1, "s2")]
    durations = {"a": ("wav_a", 1.0), "b": ("wav_b", 2.0), "c": ("wav_c", 3.0)}
    secs = rs.reel_seconds(segs, [0, 1], durations, lambda s: s.scene)
    # a, LINE_GAP, b, SCENE_GAP (the episode boundary) , c
    assert secs == pytest.approx(1.0 + rs.LINE_GAP + 2.0 + rs.SCENE_GAP + 3.0)
    assert rs.reel_seconds(segs, [1], durations, lambda s: s.scene) == 3.0


# --- finish_render(files=N) -----------------------------------------------------


def _spine_and_secs(ep_lengths):
    segs = [_seg(f"L{ep}", ep, f"scene{ep}") for ep in range(len(ep_lengths))]
    durations = {s.line_id: (f"wav_{s.line_id}", secs)
                 for s, secs in zip(segs, ep_lengths)}
    ep_secs = {s.episode: durations[s.line_id][1] for s in segs}
    return segs, durations, ep_secs


def _finish(tmp_path, segs, durations, ep_secs, calls, **kw):
    return rs.finish_render(
        segs, False, str(tmp_path / "errors.log"),
        msg_empty_input="empty input", msg_empty_selection="empty selection",
        msg_nothing_decoded="nothing decoded", msg_zero_files="zero files",
        durations=durations, ep_secs=ep_secs, out_dir=str(tmp_path),
        cache_dir=str(tmp_path / "cache"), stem="reel", columns=_columns(),
        budget=B(kbps=128), gap_key=lambda s: s.scene,
        concat_fn=_fake_concat(calls), concat_kwargs={"kbps": 128}, **kw)


def test_finish_render_files_prints_plan_then_encodes_exactly_it(tmp_path, capsys):
    segs, durations, ep_secs = _spine_and_secs([12_000.0, 8_000.0, 12_000.0])
    calls = []

    rc = _finish(tmp_path, segs, durations, ep_secs, calls, files=2)

    assert rc == 0
    out = capsys.readouterr().out
    plan_line = next(line for line in out.splitlines() if line.startswith("--files 2"))
    assert "112 kbps" in plan_line and "2 file(s)" in plan_line
    # per-file predictions, gaps between episodes included
    first = rs.encoded_size_mb(12_000.0 + rs.SCENE_GAP + 8_000.0, 112)
    second = rs.encoded_size_mb(12_000.0, 112)
    assert f"~{first:.1f} MB + ~{second:.1f} MB" in plan_line
    # printed BEFORE the first encode reports its output
    assert out.index(plan_line) < out.index("reel_00.mp3")
    # predicted count is the rendered count, at the chosen bitrate
    assert len(calls) == 2
    assert all(c["kwargs"]["kbps"] == 112 for c in calls)


def test_finish_render_impossible_files_is_rc1_and_encodes_nothing(tmp_path, capsys):
    segs, durations, ep_secs = _spine_and_secs([50_000.0, 50_000.0])
    calls = []

    rc = _finish(tmp_path, segs, durations, ep_secs, calls, files=1)

    assert rc == 1
    out = capsys.readouterr().out
    assert "render: ERROR - --files 1" in out
    assert "Re-run with --files 2" in out
    assert calls == []


def test_finish_render_without_files_keeps_budget_packing(tmp_path):
    segs, durations, ep_secs = _spine_and_secs([12_000.0, 8_000.0, 12_000.0])
    calls = []

    assert _finish(tmp_path, segs, durations, ep_secs, calls) == 0

    assert len(calls) == 3
    assert all(c["kwargs"]["kbps"] == 128 for c in calls)


def test_files_1_matches_single_file_output(tmp_path, capsys):
    """On an all-story spine, --files 1 picks the same bitrate and encodes the
    same clip/gap sequence and tracklist as --single-file (only the filename
    differs: --single-file writes an unsuffixed <stem>.mp3). Sized so the
    episode totals fit 112 kbps but the two gaps between episodes push the real
    file over it: both paths must count those gaps and settle on 96."""
    ep0 = 6_000.0 + rs.LINE_GAP + 5_000.0
    d = B(kbps=112) - 1.0 - ep0 - 7_000.0
    segs = [_seg("a", 0, "s1"), _seg("b", 0, "s1"), _seg("c", 1, "s2"), _seg("d", 2, "s3")]
    durations = {"a": ("wav_a", 6_000.0), "b": ("wav_b", 5_000.0),
                 "c": ("wav_c", 7_000.0), "d": ("wav_d", d)}
    ep_secs = {0: ep0, 1: 7_000.0, 2: d}
    assert sum(ep_secs.values()) <= B(kbps=112) < sum(ep_secs.values()) + 2 * rs.SCENE_GAP
    multi_dir, single_dir = tmp_path / "multi", tmp_path / "single"
    multi_dir.mkdir()
    single_dir.mkdir()
    multi, single = [], []

    rc_multi = _finish(multi_dir, segs, durations, ep_secs, multi, files=1)
    rc_single = rs.finish_single_file(
        segs, False, str(single_dir / "errors.log"),
        msg_empty_input="", msg_empty_selection="", msg_nothing_decoded="",
        msg_zero_story="", durations=durations, out_dir=str(single_dir),
        cache_dir=str(single_dir / "cache"), stem="reel", columns=_columns(),
        gap_key=lambda s: s.scene, story_predicate=lambda s: True,
        concat_fn=_fake_concat(single))

    assert rc_multi == rc_single == 0
    assert len(multi) == len(single) == 1
    assert multi[0]["kwargs"]["kbps"] == single[0]["kwargs"]["kbps"] == 96
    names = lambda c: [os.path.basename(w) for w in c["wav_list"]]  # noqa: E731
    assert names(multi[0]) == names(single[0])
    assert ((multi_dir / "reel_00.tracklist.csv").read_text(encoding="utf-8")
            == (single_dir / "reel.tracklist.csv").read_text(encoding="utf-8"))


# --- CLI ------------------------------------------------------------------------


def test_ds_render_rejects_files_zero_and_files_with_single_file(capsys):
    base = ["--data-dir", "d", "--oodle", "o"]
    with pytest.raises(SystemExit):
        ds_render.main(base + ["--files", "0"])
    assert "positive integer" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        ds_render.main(base + ["--files", "1", "--single-file"])
    assert "mutually exclusive" in capsys.readouterr().err


def _write_wav(path, seconds, framerate=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * int(seconds * framerate))


def test_fw_render_files_end_to_end(tmp_path, monkeypatch, capsys):
    """Through a real game CLI: measure -> plan -> pack -> encode. At a 0.5 MB
    target a file holds ~30.9 s at 128 kbps and ~35.3 s at 112, so quests of
    20 / 13 / 20 s need 3 files at 128 and fit 2 at 112 -- only because the
    1.5 s gap between the first two quests (34.5 s total) is under 35.3 s."""
    audio = tmp_path / "audio"
    audio.mkdir()
    rows = []
    for i, secs in enumerate((20.0, 13.0, 20.0)):
        _write_wav(audio / f"c{i}.wav", secs)
        rows.append({"line_id": f"c{i}", "gamescript_index": str(i), "quest": f"Q{i}",
                     "tier": "1", "speaker": "Aloy", "subtitle": "x",
                     "wav": f"audio/c{i}.wav"})
    manifest = tmp_path / "full-reel-manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    calls = []
    monkeypatch.setattr(rs, "_ffmpeg_concat", _fake_concat(calls))

    rc = fw_render.main([
        "--manifest", str(manifest), "--audio-root", str(tmp_path),
        "--out-dir", str(tmp_path / "reels"), "--cache", str(tmp_path / "cache"),
        "--errors", str(tmp_path / "errors.log"),
        "--target-mb", "0.5", "--files", "2"])

    assert rc == 0
    assert "--files 2: 112 kbps" in capsys.readouterr().out
    assert [os.path.basename(c["out_mp3"]) for c in calls] == [
        "fw_story_reel_00.mp3", "fw_story_reel_01.mp3"]
    assert all(c["kwargs"]["kbps"] == 112 for c in calls)
