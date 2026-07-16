import os
import shutil
import subprocess
import wave

import pytest

from deciwaves.engine import audio_clip as ac
from deciwaves.engine import render as rs
from deciwaves.engine.story_order import Segment, write_playlist


def _seg(is_side, line_id, scene="sq_cs00_s00100", category="cutscene", episode=0):
    return Segment(episode=episode, is_side=is_side, pos=0.0, section=0, scene=scene,
                   line_index=0, track_index=0, category=category, speaker="Sam",
                   subtitle="hi", stream_path="x.core.stream", line_id=line_id)


def _write_wav(path, nchannels, seconds, framerate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(nchannels)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nchannels * int(seconds * framerate))


needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed")


@needs_ffmpeg
def test_normalize_wav_forces_canonical_stereo_48k(tmp_path):
    src = tmp_path / "mono.wav"
    _write_wav(src, nchannels=1, seconds=1.0)
    dst = rs.normalize_wav(str(src), str(tmp_path / "norm"))
    with wave.open(dst, "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == rs.SR
        assert w.getsampwidth() == 2


@needs_ffmpeg
def test_concat_of_mixed_channel_clips_preserves_duration(tmp_path):
    # 1 s mono line + 1 s 6-channel cutscene track => 2 s out. Without
    # normalization the concat demuxer reframes the 6ch clip and the total
    # blows up (this is the "clips playing fast" bug).
    mono = tmp_path / "mono.wav"
    surround = tmp_path / "surround.wav"
    _write_wav(mono, nchannels=1, seconds=1.0)
    _write_wav(surround, nchannels=6, seconds=1.0)
    out = tmp_path / "out.mp3"
    rs._ffmpeg_concat([str(mono), str(surround)], str(out),
                      str(tmp_path / "list.txt"), str(tmp_path / "norm"))
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
        capture_output=True, text=True).stdout.strip())
    assert abs(dur - 2.0) < 0.1


def test_budget_seconds_stays_under_290_buffer():
    # The naive ideal budget packs files that encode to ~293 MB (over the
    # 290 MB buffer). The overhead-adjusted budget must keep real output <= 290 MB.
    secs = rs.budget_seconds()
    real_bytes = secs * 16000 * (1 + rs.MP3_OVERHEAD)
    assert real_bytes <= 290_000_000
    assert secs < rs.BUDGET_SECONDS  # tighter than the buggy ideal


def test_budget_seconds_custom_target():
    secs = rs.budget_seconds(target_mb=200)
    assert secs * 16000 * (1 + rs.MP3_OVERHEAD) <= 200_000_000


def test_budget_seconds_scales_with_bitrate():
    # Lower bitrate fits more seconds per file, and the real encoded bytes at
    # that bitrate must still stay under the target (bytes/s = kbps*1000/8).
    assert rs.budget_seconds(kbps=96) > rs.budget_seconds(kbps=128)
    secs = rs.budget_seconds(target_mb=285, kbps=96)
    assert secs * (96 * 1000 / 8) * (1 + rs.MP3_OVERHEAD) <= 285_000_000


def test_pack_groups_whole_episodes_under_budget():
    assert rs.pack_episodes([(0, 100), (1, 100), (2, 100)], budget=250) == [[0, 1], [2]]


def test_pack_oversized_episode_gets_own_file():
    assert rs.pack_episodes([(0, 50), (1, 400), (2, 50)], budget=250) == [[0], [1], [2]]


def test_pack_preserves_episode_order():
    assert rs.pack_episodes([(2, 10), (0, 10), (1, 10)], budget=100) == [[0, 1, 2]]


def test_pack_empty():
    assert rs.pack_episodes([], budget=250) == []


def test_format_ts():
    assert rs.format_ts(0) == "0:00:00"
    assert rs.format_ts(3661) == "1:01:01"


def test_main_story_only_keeps_spine_drops_side():
    segs = [_seg(0, "a"), _seg(1, "b"), _seg(0, "c"), _seg(1, "d")]
    kept = rs.main_story_only(segs)
    assert [s.line_id for s in kept] == ["a", "c"]


def test_main_story_only_preserves_order():
    segs = [_seg(0, "c"), _seg(0, "a"), _seg(0, "b")]
    assert [s.line_id for s in rs.main_story_only(segs)] == ["c", "a", "b"]


def test_main_story_only_drops_non_story_cutscene_groups():
    # cs71 (Battlefield) leaks EX-grenade/BB chatter into the spine; cull it while
    # keeping story cutscenes (cs02) and mission lines.
    segs = [
        _seg(0, "story_cut", scene="sq_cs02_s00400", category="cutscene"),
        _seg(0, "battlefield", scene="sq_cs71_s00270_c101", category="cutscene"),
        _seg(0, "mission", scene="lines_m00030", category="mission"),
    ]
    kept = rs.main_story_only(segs, non_story_cs_groups={"cs71"})
    assert [s.line_id for s in kept] == ["story_cut", "mission"]


def test_main_story_only_cs_cull_only_applies_to_cutscene_category():
    # A non-cutscene segment whose scene happens to contain a culled group id is kept:
    # the cull is scoped to cutscene tracks, not any scene string.
    segs = [_seg(0, "m", scene="sq_cs71_weird", category="mission")]
    assert [s.line_id for s in rs.main_story_only(segs, non_story_cs_groups={"cs71"})] == ["m"]


def test_main_story_only_default_no_cs_cull():
    # Backward compatible: with no group set, cutscene groups are not culled.
    segs = [_seg(0, "battlefield", scene="sq_cs71_s00270_c101", category="cutscene")]
    assert [s.line_id for s in rs.main_story_only(segs)] == ["battlefield"]


def test_file_stem_distinguishes_main_story_reel():
    # Distinct base names so a main-story render never clobbers the full reel.
    assert rs.file_stem(main_story=False) == "phase_d"
    assert rs.file_stem(main_story=True) == "phase_d_main"
    assert rs.file_stem(main_story=True) != rs.file_stem(main_story=False)


def test_silence_wav_duration(tmp_path):
    p = rs.silence_wav(0.5, str(tmp_path))
    with wave.open(p, "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - 0.5) < 1e-3


def test_silence_wav_interrupted_write_does_not_poison_cache(tmp_path, monkeypatch):
    """Regression for issue #18: an interrupted silence_wav write (Ctrl-C /
    crash mid-write) must not leave a truncated .wav at the final cache path
    -- silence_wav's cache check is a bare `isfile`, so ANY file sitting there
    is treated as valid forever."""
    real_wave_open = rs.wave.open

    def flaky_open(path, mode):
        with open(path, "wb") as f:
            f.write(b"PARTIAL-GARBAGE-NOT-A-COMPLETE-WAVE-FILE")
        raise RuntimeError("simulated interrupt mid-write (Ctrl-C)")

    monkeypatch.setattr(rs.wave, "open", flaky_open)

    with pytest.raises(RuntimeError):
        rs.silence_wav(0.5, str(tmp_path))

    final_path = os.path.join(str(tmp_path), "silence_500ms.wav")
    assert not os.path.isfile(final_path), \
        "interrupted write must not poison the cache at the final path"
    assert os.listdir(str(tmp_path)) == [], "no tmp file should be left behind"

    # Cache must not be permanently poisoned: a real run afterwards succeeds.
    monkeypatch.setattr(rs.wave, "open", real_wave_open)
    p = rs.silence_wav(0.5, str(tmp_path))
    assert os.path.isfile(p)
    with wave.open(p, "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - 0.5) < 1e-3


@needs_ffmpeg
def test_normalize_wav_interrupted_write_does_not_poison_cache(tmp_path, monkeypatch):
    """Regression for issue #18: an ffmpeg normalize run that partially writes
    the destination then fails must not leave a truncated file at the cache
    path that a later run's `isfile and getsize > 44` check would accept."""
    src = tmp_path / "mono.wav"
    _write_wav(src, nchannels=1, seconds=1.0)
    norm_dir = tmp_path / "norm"

    real_run = rs.subprocess.run

    def flaky_run(args, **kwargs):
        out_path = args[-1]
        with open(out_path, "wb") as f:
            f.write(b"GARBAGE-OVER-44-BYTES-BUT-NOT-A-REAL-WAVE-FILE-AT-ALL")
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="simulated crash mid-write")

    monkeypatch.setattr(rs.subprocess, "run", flaky_run)
    with pytest.raises(RuntimeError):
        rs.normalize_wav(str(src), str(norm_dir))

    dst = os.path.join(str(norm_dir), os.path.basename(str(src)))
    assert not os.path.isfile(dst), \
        "failed normalize must not poison the cache at the final path"
    assert not os.path.isdir(norm_dir) or os.listdir(norm_dir) == [], \
        "no tmp file should be left behind after a failed normalize"

    # Cache must not be permanently poisoned: a real run afterwards succeeds.
    monkeypatch.setattr(rs.subprocess, "run", real_run)
    out = rs.normalize_wav(str(src), str(norm_dir))
    assert os.path.isfile(out)


def test_load_keepspans_parses_map(tmp_path):
    p = tmp_path / "ks.csv"
    p.write_text(
        "stream_path,line_id,speech_ratio,keep_spans,dropped\n"
        "a.core.stream,sq_cs00#track0,0.5,0.65:2.35;3.0:4.0,0\n"
        "g.core.stream,sq_cs71#track0,0.01,,1\n",
        encoding="utf-8")
    m = rs.load_keepspans(str(p))
    assert m["a.core.stream"] == ([(0.65, 2.35), (3.0, 4.0)], False)
    assert m["g.core.stream"] == ([], True)


def test_load_keepspans_missing_file_is_empty():
    assert rs.load_keepspans("does/not/exist.csv") == {}


# --- main(): zero-decode must be a loud failure, not a silent zero-clip "success" ---
# Real-world repro: every one of 2,049 vgmstream-cli calls died on a Windows Store
# Python (STATUS_DLL_NOT_FOUND) and main() returned 0 with zero reels produced.

def _playlist_segs(n_good=0, n_bad=0):
    segs = []
    for i in range(n_good):
        segs.append(Segment(episode=0, is_side=0, pos=float(i), section=0,
                             scene="sq_cs00_s00100", line_index=i, track_index=0,
                             category="cutscene", speaker="Sam", subtitle="hi",
                             stream_path=f"good/stream{i}.core.stream", line_id=f"Lgood{i}"))
    for i in range(n_bad):
        segs.append(Segment(episode=0, is_side=0, pos=float(n_good + i), section=0,
                             scene="sq_cs00_s00100", line_index=n_good + i, track_index=0,
                             category="cutscene", speaker="Sam", subtitle="bye",
                             stream_path=f"bad/stream{i}.core.stream", line_id=f"Lbad{i}"))
    return segs


def _render_argv(tmp_path, playlist, errors, extra=()):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return [
        "--data-dir", str(data_dir),
        "--oodle", str(tmp_path / "fake_oodle.dll"),
        "--playlist", str(playlist),
        "--out-dir", str(tmp_path / "out-audio"),
        "--cache", str(tmp_path / "cache"),
        "--errors", str(errors),
        *extra,
    ]


def test_render_main_zero_decode_returns_1_and_prints_actionable_error(tmp_path, monkeypatch, capsys):
    """Every segment fails to decode (idx has no archives -> clip_wav raises
    ClipError for each). main() must return 1, never write a done-marker via the
    chain runner, and its message must name the errors file, `deciwaves doctor`,
    and the README's Windows Store Python troubleshooting note."""
    monkeypatch.chdir(tmp_path)
    playlist = tmp_path / "playlist.csv"
    write_playlist(_playlist_segs(n_good=0, n_bad=2), str(playlist))
    errors = tmp_path / "render-errors.log"

    rc = rs.main(_render_argv(tmp_path, playlist, errors))

    assert rc == 1
    out = capsys.readouterr().out
    assert "render: decoded 0 clips, 2 failed" in out
    assert str(errors) in out
    assert "deciwaves doctor" in out
    assert "Windows Store Python" in out


def test_render_main_all_decode_ok_but_no_segments_returns_0(tmp_path, monkeypatch, capsys):
    """An empty playlist (nothing to decode at all) must not be treated as the
    zero-decode failure -- there's simply nothing to do."""
    monkeypatch.chdir(tmp_path)
    playlist = tmp_path / "playlist.csv"
    write_playlist([], str(playlist))
    errors = tmp_path / "render-errors.log"

    rc = rs.main(_render_argv(tmp_path, playlist, errors))

    assert rc == 0
    out = capsys.readouterr().out
    assert "render: decoded 0 clips, 0 failed" in out


@needs_ffmpeg
def test_render_main_partial_success_returns_0_with_summary(tmp_path, monkeypatch, capsys):
    """One clip decodes, one fails: partial success keeps returning 0, but the
    summary line still reports the failure count."""
    monkeypatch.chdir(tmp_path)
    playlist = tmp_path / "playlist.csv"
    write_playlist(_playlist_segs(n_good=1, n_bad=1), str(playlist))
    errors = tmp_path / "render-errors.log"

    def fake_clip_wav(idx, stream_path, cache_dir, vgmstream=None):
        if stream_path.startswith("good/"):
            os.makedirs(cache_dir, exist_ok=True)
            wav_path = os.path.join(cache_dir, "good.wav")
            _write_wav(wav_path, nchannels=1, seconds=1.0)
            return wav_path, 1.0
        raise ac.ClipError(f"vgmstream failed for {stream_path}: exit code 1")

    monkeypatch.setattr(ac, "clip_wav", fake_clip_wav)

    rc = rs.main(_render_argv(tmp_path, playlist, errors, extra=["--min-silence", "0"]))

    assert rc == 0
    out = capsys.readouterr().out
    assert "render: decoded 1 clips, 1 failed" in out


# --- accumulate_episode_seconds / assemble_reels: the shared render assembly kit
# (issue #26). Characterization tests against the extracted helper signatures: DS
# (engine/render.py), HZD (games/hzd/render.py) and FW (games/fw/render.py) main()s
# all now call these two functions instead of each carrying their own copy of the
# measure -> gap-accounting -> pack -> concat -> tracklist loop.

def test_accumulate_episode_seconds_prices_gaps_by_scene_change(tmp_path):
    """First line in an episode costs no gap; a same-key line costs LINE_GAP; a
    key change within the same episode costs SCENE_GAP. A new episode resets."""
    segs = [
        _seg(0, "a", scene="s1", episode=0),
        _seg(0, "b", scene="s1", episode=0),   # same scene as prev -> LINE_GAP
        _seg(0, "c", scene="s2", episode=0),   # different scene -> SCENE_GAP
        _seg(0, "d", scene="s3", episode=1),   # new episode -> first line, no gap
    ]
    durs = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}

    def dur_of(s):
        return f"wav_{s.line_id}", durs[s.line_id]

    errors = tmp_path / "errors.log"
    results, ep_secs, n_failed = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
        errors_path=str(errors), catch=Exception)

    assert n_failed == 0
    assert results == {"a": ("wav_a", 1.0), "b": ("wav_b", 2.0),
                       "c": ("wav_c", 3.0), "d": ("wav_d", 4.0)}
    assert ep_secs[0] == pytest.approx(1.0 + (rs.LINE_GAP + 2.0) + (rs.SCENE_GAP + 3.0))
    assert ep_secs[1] == pytest.approx(4.0)


def test_accumulate_episode_seconds_gap_key_can_be_any_field():
    """The "same scene" key is caller-supplied (DS/HZD key on `scene`, FW keys on
    `quest`) -- any callable works, not just a `scene` attribute lookup."""
    segs = [_seg(0, "a", episode=0), _seg(0, "b", episode=0)]

    def dur_of(s):
        return None, 1.0

    results, ep_secs, _ = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.line_id, err_key=lambda s: s.line_id,
        errors_path=os.devnull, catch=Exception)
    # every line_id is distinct -> every non-first line is a "new scene" -> SCENE_GAP
    assert ep_secs[0] == pytest.approx(1.0 + rs.SCENE_GAP + 1.0)


def test_accumulate_episode_seconds_logs_and_skips_failures(tmp_path):
    """A `dur_of` failure in `catch` is fail-soft: logged with the line id and the
    caller's `err_key`, then skipped -- the loop keeps going for later segments."""
    segs = [_seg(0, "good", episode=0), _seg(0, "bad", episode=0)]

    class Boom(Exception):
        pass

    def dur_of(s):
        if s.line_id == "bad":
            raise Boom("kaboom")
        return "wav_good", 1.0

    errors = tmp_path / "errors.log"
    results, ep_secs, n_failed = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
        errors_path=str(errors), catch=Boom)

    assert n_failed == 1
    assert set(results) == {"good"}
    assert ep_secs[0] == pytest.approx(1.0)   # only the good clip contributed
    err_text = errors.read_text(encoding="utf-8")
    assert "bad\tbad\tkaboom" in err_text


def test_accumulate_episode_seconds_uncaught_exception_type_propagates(tmp_path):
    """Only exception types in `catch` are fail-soft; anything else still aborts the
    render (mirrors DS only catching ClipError, HZD/FW their own narrower tuples)."""
    segs = [_seg(0, "a", episode=0)]

    def dur_of(s):
        raise ValueError("not caught by this caller's `catch`")

    with pytest.raises(ValueError):
        rs.accumulate_episode_seconds(
            segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
            errors_path=str(tmp_path / "errors.log"), catch=KeyError)


def test_accumulate_episode_seconds_parallel_matches_serial(tmp_path):
    """The `jobs` knob (issue #41) only parallelizes the per-clip decode; the
    accumulated results, per-episode seconds and failure count must be identical
    to the serial (jobs=1) run, regardless of worker count."""
    import time as _time

    segs = [_seg(0, f"L{i}", scene=f"s{i % 3}", episode=i % 2) for i in range(30)]
    durs = {s.line_id: float(i + 1) for i, s in enumerate(segs)}

    def dur_of(s):
        # jitter so completion order != input order under a pool
        _time.sleep((hash(s.line_id) % 5) * 0.001)
        return f"wav_{s.line_id}", durs[s.line_id]

    serial = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
        errors_path=str(tmp_path / "e_serial.log"), catch=Exception, jobs=1)
    parallel = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
        errors_path=str(tmp_path / "e_parallel.log"), catch=Exception, jobs=8)

    assert parallel[0] == serial[0]        # results dict
    assert parallel[1] == serial[1]        # ep_secs
    assert parallel[2] == serial[2] == 0   # n_failed


def test_accumulate_episode_seconds_parallel_failure_is_fail_soft(tmp_path):
    """Under concurrency a clip whose decode raises (in `catch`) is logged and
    skipped; the pool keeps running and every other clip still decodes."""
    segs = [_seg(0, f"L{i}", scene="s", episode=0) for i in range(20)]
    bad = {"L3", "L7", "L11"}

    def dur_of(s):
        if s.line_id in bad:
            raise ac.ClipError(f"decode failed for {s.line_id}")
        return f"wav_{s.line_id}", 1.0

    errors = tmp_path / "errors.log"
    results, ep_secs, n_failed = rs.accumulate_episode_seconds(
        segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
        errors_path=str(errors), catch=ac.ClipError, jobs=8)

    assert n_failed == 3
    assert set(results) == {s.line_id for s in segs} - bad
    # errors file is line-atomic: exactly 3 well-formed lines, none interleaved
    lines = [ln for ln in errors.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 3
    assert {ln.split("\t")[0] for ln in lines} == bad
    for ln in lines:
        assert len(ln.split("\t")) == 3    # line_id \t err_key \t message, uncorrupted


def test_accumulate_episode_seconds_parallel_uncaught_still_propagates(tmp_path):
    """An exception type outside `catch` still aborts, even under a pool."""
    segs = [_seg(0, f"L{i}", episode=0) for i in range(10)]

    def dur_of(s):
        if s.line_id == "L4":
            raise ValueError("not in catch")
        return None, 1.0

    with pytest.raises(ValueError):
        rs.accumulate_episode_seconds(
            segs, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.line_id,
            errors_path=str(tmp_path / "errors.log"), catch=KeyError, jobs=8)


def test_accumulate_episode_seconds_empty_segs():
    results, ep_secs, n_failed = rs.accumulate_episode_seconds(
        [], lambda s: (None, 0.0), gap_key=lambda s: s.scene,
        err_key=lambda s: s.line_id, errors_path=os.devnull, catch=Exception)
    assert results == {} and ep_secs == {} and n_failed == 0


def _fake_concat(calls):
    def concat_fn(wav_list, out_mp3, list_path, norm_dir, **kwargs):
        calls.append({"wav_list": list(wav_list), "out_mp3": out_mp3,
                      "list_path": list_path, "norm_dir": norm_dir, "kwargs": kwargs})
        with open(out_mp3, "w", encoding="utf-8") as f:
            f.write("fake mp3\n")
    return concat_fn


def _hzd_style_columns():
    return rs.ReelColumns(
        header=["timestamp", "scene", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [rs.format_ts(t), s.scene, s.speaker, s.subtitle, s.line_id])


def test_assemble_reels_inserts_gap_silence_matching_scene_changes(tmp_path):
    """The assembled wav_list interleaves LINE_GAP/SCENE_GAP silence exactly where
    `gap_key` changes, mirroring accumulate_episode_seconds's own gap pricing."""
    segs = [
        _seg(0, "a", scene="s1", episode=0),
        _seg(0, "b", scene="s1", episode=0),
        _seg(0, "c", scene="s2", episode=0),
    ]
    durations = {"a": ("wav_a", 1.0), "b": ("wav_b", 1.0), "c": ("wav_c", 1.0)}
    ep_secs = {0: 1.0 + (rs.LINE_GAP + 1.0) + (rs.SCENE_GAP + 1.0)}
    calls = []
    out_dir = tmp_path / "out"; out_dir.mkdir()

    n_files = rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(out_dir),
        cache_dir=str(tmp_path / "cache"), stem="reel", columns=_hzd_style_columns(),
        budget=1000, gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n_files == 1
    assert len(calls) == 1
    wav_list = calls[0]["wav_list"]
    assert wav_list[0] == "wav_a"
    assert wav_list[2] == "wav_b"
    assert wav_list[4] == "wav_c"
    # the two silence gaps are real cached files, distinguishable by their ms name
    assert "400ms" in os.path.basename(wav_list[1])    # LINE_GAP = 0.4s
    assert "1500ms" in os.path.basename(wav_list[3])   # SCENE_GAP = 1.5s
    assert len(wav_list) == 5


def test_assemble_reels_writes_tracklist_csv(tmp_path):
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 2.0)}
    ep_secs = {0: 2.0}
    calls = []

    rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="myreel", columns=_hzd_style_columns(), budget=1000,
        gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    tracklist = tmp_path / "myreel_00.tracklist.csv"
    assert tracklist.is_file()
    rows = tracklist.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "timestamp,scene,speaker,subtitle,line_id"
    assert rows[1] == "0:00:00,s1,Sam,hi,a"


def test_assemble_reels_columns_shape_differs_per_game(tmp_path):
    """`columns` lets the tracklist shape genuinely differ per game (DS ships
    episode+category, HZD ships scene, FW ships quest) without the loop caring."""
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 1.0)}
    ep_secs = {0: 1.0}
    calls = []
    ds_columns = rs.ReelColumns(
        header=["timestamp", "episode", "category", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [rs.format_ts(t), s.episode, s.category, s.speaker,
                             s.subtitle, s.line_id])

    rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="ds_reel", columns=ds_columns, budget=1000, gap_key=lambda s: s.scene,
        concat_fn=_fake_concat(calls))

    rows = (tmp_path / "ds_reel_00.tracklist.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "timestamp,episode,category,speaker,subtitle,line_id"
    assert rows[1] == "0:00:00,0,cutscene,Sam,hi,a"


def test_assemble_reels_respects_budget_and_splits_files(tmp_path):
    """Episodes over budget in aggregate split into separate reel files, same as
    `pack_episodes` alone -- assemble_reels doesn't change the packing policy."""
    segs = [_seg(0, "a", scene="s1", episode=0), _seg(0, "b", scene="s2", episode=1)]
    durations = {"a": ("wav_a", 100.0), "b": ("wav_b", 100.0)}
    ep_secs = {0: 100.0, 1: 100.0}
    calls = []

    n_files = rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="reel", columns=_hzd_style_columns(), budget=150.0,
        gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n_files == 2
    assert len(calls) == 2
    assert (tmp_path / "reel_00.tracklist.csv").is_file()
    assert (tmp_path / "reel_01.tracklist.csv").is_file()


def test_assemble_reels_skips_episodes_with_no_decoded_segments(tmp_path):
    """A segment missing from `durations` (e.g. its decode failed) is dropped from
    its reel; a packed group left with nothing decoded writes no file at all."""
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {}   # "a" never decoded
    ep_secs = {0: 1.0}
    calls = []

    n_files = rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="reel", columns=_hzd_style_columns(), budget=1000,
        gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls))

    assert n_files == 0
    assert calls == []
    assert not (tmp_path / "reel_00.tracklist.csv").exists()


def test_assemble_reels_forwards_concat_kwargs(tmp_path):
    """DS forwards `kbps=args.bitrate` through to `_ffmpeg_concat`; assemble_reels
    must pass caller-supplied concat_kwargs through unchanged."""
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": ("wav_a", 1.0)}
    ep_secs = {0: 1.0}
    calls = []

    rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="reel", columns=_hzd_style_columns(), budget=1000,
        gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls),
        concat_kwargs={"kbps": 96})

    assert calls[0]["kwargs"] == {"kbps": 96}


def test_assemble_reels_uses_custom_silence_and_concat_fns(tmp_path):
    """FW's --uniform-mono path substitutes its own silence generator and concat
    implementation; assemble_reels must route through whatever is supplied instead
    of always calling the module's own _ffmpeg_concat/silence_wav."""
    segs = [_seg(0, "a", scene="s1", episode=0), _seg(0, "b", scene="s2", episode=0)]
    durations = {"a": ("wav_a", 1.0), "b": ("wav_b", 1.0)}
    ep_secs = {0: 1.0 + rs.SCENE_GAP + 1.0}
    silence_calls = []

    def fake_silence(seconds, cache_dir):
        silence_calls.append(seconds)
        return f"mono_silence_{seconds}.wav"

    calls = []
    rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"),
        stem="reel", columns=_hzd_style_columns(), budget=1000,
        gap_key=lambda s: s.scene, concat_fn=_fake_concat(calls),
        silence_fn=fake_silence)

    assert sorted(silence_calls) == sorted([rs.LINE_GAP, rs.SCENE_GAP])
    assert calls[0]["wav_list"] == ["wav_a", "mono_silence_1.5.wav", "wav_b"]


@needs_ffmpeg
def test_assemble_reels_default_concat_and_silence_produce_real_mp3(tmp_path):
    """End-to-end with the real defaults (no concat_fn/silence_fn override): this is
    the exact wiring DS/HZD/FW's main()s rely on."""
    wav_a = tmp_path / "a.wav"
    _write_wav(wav_a, nchannels=1, seconds=1.0)
    segs = [_seg(0, "a", scene="s1", episode=0)]
    durations = {"a": (str(wav_a), 1.0)}
    ep_secs = {0: 1.0}
    out_dir = tmp_path / "out"; out_dir.mkdir()

    n_files = rs.assemble_reels(
        segs, ep_secs, durations, out_dir=str(out_dir),
        cache_dir=str(tmp_path / "cache"), stem="reel", columns=_hzd_style_columns(),
        budget=1000, gap_key=lambda s: s.scene)

    assert n_files == 1
    out_mp3 = out_dir / "reel_00.mp3"
    assert out_mp3.is_file() and out_mp3.stat().st_size > 0
