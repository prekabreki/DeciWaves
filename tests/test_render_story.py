import shutil
import subprocess
import wave

import pytest

from deciwaves.engine import render as rs
from deciwaves.engine.story_order import Segment


def _seg(is_side, line_id, scene="sq_cs00_s00100", category="cutscene"):
    return Segment(episode=0, is_side=is_side, pos=0.0, section=0, scene=scene,
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
