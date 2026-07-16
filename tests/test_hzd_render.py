import wave

from deciwaves.games.hzd import render
from deciwaves.games.hzd.render import mq_rank, build_spine, decode_spine_clips, SpineItem


def test_mq_rank_parses_variants():
    assert mq_rank("mq04_mothersheart") == 4.0
    assert mq_rank("mq01_papooserider") == 1.0
    assert mq_rank("mq01_5_giftfromthepast") == 1.5
    assert mq_rank("mq15.5_rallytheforces") == 15.5
    assert mq_rank("mq16_thefaceofextinction") == 16.0
    assert mq_rank("dlc1_tba03") is None
    assert mq_rank("banditcamps/bc_ic_jom") is None


def test_build_spine_orders_filters_and_assigns_episodes():
    catalog = {
        "MQ04_a": {"category": "mission", "subtitle_en": "Four A", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "1"},
        "MQ04_b": {"category": "mission", "subtitle_en": "Four B", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "0"},
        "MQ06_a": {"category": "mission", "subtitle_en": "Six", "speaker_name": "erend",
                   "scene": "mq06_aftermath", "line_index": "0"},
        "AMB":    {"category": "ambient", "subtitle_en": "bark", "speaker_name": "x",
                   "scene": "mq04_mothersheart", "line_index": "5"},
        "SIDE":   {"category": "mission", "subtitle_en": "side", "speaker_name": "y",
                   "scene": "tcb01_foo", "line_index": "0"},
    }
    manifest = [
        {"clip_row": "10", "line_id": "MQ04_a", "tier": "S"},
        {"clip_row": "11", "line_id": "MQ04_b", "tier": "1"},
        {"clip_row": "12", "line_id": "MQ06_a", "tier": "S"},
        {"clip_row": "13", "line_id": "AMB",    "tier": "S"},   # ambient -> excluded
        {"clip_row": "14", "line_id": "SIDE",   "tier": "S"},   # side quest -> excluded
        {"clip_row": "15", "line_id": "MQ04_a", "tier": "3"},   # unbound dup -> excluded
    ]
    clip_index = {10: {"offset": "100", "a_bytes": "50"},
                  11: {"offset": "200", "a_bytes": "60"},
                  12: {"offset": "300", "a_bytes": "70"}}
    spine = build_spine(manifest, catalog, clip_index)

    # only the 3 main-quest bound story lines, mq04 (line_index 0 then 1) then mq06
    assert [s.line_id for s in spine] == ["MQ04_b", "MQ04_a", "MQ06_a"]
    # whole quests become episodes for packing: mq04 -> 0, mq06 -> 1
    assert [s.episode for s in spine] == [0, 0, 1]
    # decode coords carried through from clip_index
    assert spine[0].offset == 200 and spine[0].a_bytes == 60
    assert spine[0].speaker == "aloy" and spine[0].subtitle == "Four B"


def test_build_spine_interleaves_side_quests_by_episode_map():
    """With an episode_map, side/DLC questlines interleave at their unlock rank;
    main quests keep their mq# rank. Nothing is dropped (keep side quests + tidbits)."""
    catalog = {
        "MQ04_a": {"category": "mission", "subtitle_en": "Four", "speaker_name": "aloy",
                   "scene": "mq04_mothersheart", "line_index": "0"},
        "MQ06_a": {"category": "mission", "subtitle_en": "Six", "speaker_name": "erend",
                   "scene": "mq06_aftermath", "line_index": "0"},
        "SIDE_a": {"category": "other", "subtitle_en": "Side", "speaker_name": "nil",
                   "scene": "tnb01_theonethatgotaway/conv", "line_index": "0"},
        "DLC_a":  {"category": "dlc", "subtitle_en": "Cut", "speaker_name": "aratak",
                   "scene": "dlc1_tba03/base", "line_index": "0"},
        "UNK_a":  {"category": "other", "subtitle_en": "Mystery", "speaker_name": "x",
                   "scene": "zzz_unmapped/conv", "line_index": "0"},
    }
    manifest = [{"clip_row": str(i), "line_id": lid, "tier": "S"}
                for i, lid in enumerate(["MQ04_a", "MQ06_a", "SIDE_a", "DLC_a", "UNK_a"])]
    clip_index = {i: {"offset": str(i * 10), "a_bytes": "50"} for i in range(5)}
    em = {"tnb01_theonethatgotaway": 4.5, "dlc1_tba03": 12.5}

    spine = build_spine(manifest, catalog, clip_index, episode_map=em)
    # mq04(4.0) -> side tnb01(4.5) -> mq06(6.0) -> dlc(12.5) -> unmapped(end, not dropped)
    assert [s.line_id for s in spine] == ["MQ04_a", "SIDE_a", "MQ06_a", "DLC_a", "UNK_a"]


def test_scenes_within_quest_ordered_by_line_sequence_not_alphabetical():
    """Within a quest, scenes must order by their embedded line sequence, not alphabet.
    Prologue: 'thewalk' (Dial_020..) precedes 'namingceremony' (Dial_220..) even though
    'namingceremony' < 'thewalk' alphabetically."""
    catalog = {
        "MQ010_cut_Prologue_Dial_020": {"category": "mission", "subtitle_en": "walk a",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_thewalk", "line_index": "0"},
        "MQ010_cut_Prologue_Dial_040": {"category": "mission", "subtitle_en": "walk b",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_thewalk", "line_index": "1"},
        "MQ010_cut_Prologue_Dial_220": {"category": "mission", "subtitle_en": "ceremony a",
            "speaker_name": "rost", "scene": "mq01_papooserider/mq010_cut_namingceremony", "line_index": "0"},
    }
    manifest = [{"clip_row": str(i), "line_id": lid, "tier": "S"}
                for i, lid in enumerate(catalog)]
    clip_index = {i: {"offset": str(i), "a_bytes": "1"} for i in range(len(catalog))}
    spine = build_spine(manifest, catalog, clip_index)
    assert [s.scene.split("/")[-1] for s in spine] == [
        "mq010_cut_thewalk", "mq010_cut_thewalk", "mq010_cut_namingceremony"]


def test_build_spine_skips_lines_without_clip_coords():
    catalog = {"MQ04_a": {"category": "mission", "subtitle_en": "A", "speaker_name": "aloy",
                          "scene": "mq04_mothersheart", "line_index": "0"}}
    manifest = [{"clip_row": "99", "line_id": "MQ04_a", "tier": "S"}]
    spine = build_spine(manifest, catalog, {})   # clip_row 99 absent
    assert spine == []


# --- decode_spine_clips: fail-soft per-clip decode/read (issue #19) ---

def _write_silent_wav(path, n_frames=48000, rate=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n_frames)


class _FakeDsar:
    """Raises ValueError for offsets in `fail_offsets` (mirrors a bad-offset
    dsar_archive/fw_stream read -- see test_dsar_archive.py), else succeeds."""

    def __init__(self, fail_offsets):
        self.fail_offsets = set(fail_offsets)

    def read(self, offset, length):
        if offset in self.fail_offsets:
            raise ValueError(f"no chunk contains offset {offset} in fake.core")
        return b"\x00" * length


def test_decode_spine_clips_skips_bad_read_and_continues(tmp_path, monkeypatch):
    spine = [
        SpineItem(episode=0, scene="mq01", line_index=0, speaker="aloy", subtitle="a",
                  line_id="L0", clip_row=0, offset=0, a_bytes=10),
        SpineItem(episode=0, scene="mq01", line_index=1, speaker="aloy", subtitle="b",
                  line_id="L1", clip_row=1, offset=100, a_bytes=10),
        SpineItem(episode=0, scene="mq01", line_index=2, speaker="aloy", subtitle="c",
                  line_id="L2", clip_row=2, offset=200, a_bytes=10),
    ]
    monkeypatch.setattr(
        "deciwaves.games.hzd.render.decode_wem_to_wav",
        lambda wem_bytes, wav_path: _write_silent_wav(wav_path),
    )
    cache_dir = tmp_path / "cache"; cache_dir.mkdir()
    errors = tmp_path / "render-errors.log"

    decoded, ep_secs, skipped = decode_spine_clips(
        spine, _FakeDsar(fail_offsets={100}), str(cache_dir), str(errors))

    assert skipped == 1
    assert set(decoded) == {"L0", "L2"}    # L1's read raised -> skipped, loop continued
    assert ep_secs[0] > 0                  # the two good clips still contributed duration
    err_text = errors.read_text(encoding="utf-8")
    assert "L1\t1\t" in err_text           # line id + clip row logged
    assert "no chunk contains offset 100" in err_text


def test_decode_spine_clips_parallel_matches_serial_and_is_fail_soft(tmp_path, monkeypatch):
    """--jobs>1 must yield the same decoded set / ep_secs / skip count as serial,
    and a per-clip decode failure under the pool is logged + skipped, not fatal
    (issue #41)."""
    import time as _time

    spine = [
        SpineItem(episode=i % 2, scene=f"mq0{i % 3}", line_index=i, speaker="aloy",
                  subtitle=f"line {i}", line_id=f"L{i}", clip_row=i, offset=i * 100,
                  a_bytes=10)
        for i in range(24)
    ]
    fail_offsets = {300, 700, 1100}   # three clips' reads raise ValueError

    def decode(wem_bytes, wav_path):
        _write_silent_wav(wav_path)

    monkeypatch.setattr("deciwaves.games.hzd.render.decode_wem_to_wav", decode)

    def run(jobs, tag):
        dsar = _FakeDsar(fail_offsets=fail_offsets)
        # add jitter so worker completion order differs from spine order
        orig = dsar.read
        def jittered(offset, length):
            _time.sleep((offset // 100 % 4) * 0.001)
            return orig(offset, length)
        dsar.read = jittered
        cache = tmp_path / f"cache_{tag}"; cache.mkdir()
        errors = tmp_path / f"err_{tag}.log"
        return decode_spine_clips(spine, dsar, str(cache), str(errors), jobs=jobs)

    s_decoded, s_ep, s_skip = run(1, "serial")
    p_decoded, p_ep, p_skip = run(8, "parallel")

    assert set(p_decoded) == set(s_decoded)
    assert p_ep == s_ep
    assert p_skip == s_skip == 3


def test_decode_spine_clips_no_failures_no_skips(tmp_path, monkeypatch):
    spine = [SpineItem(episode=0, scene="mq01", line_index=0, speaker="aloy", subtitle="a",
                       line_id="L0", clip_row=0, offset=0, a_bytes=10)]
    monkeypatch.setattr(
        "deciwaves.games.hzd.render.decode_wem_to_wav",
        lambda wem_bytes, wav_path: _write_silent_wav(wav_path),
    )
    cache_dir = tmp_path / "cache"; cache_dir.mkdir()
    errors = tmp_path / "render-errors.log"

    decoded, ep_secs, skipped = decode_spine_clips(
        spine, _FakeDsar(fail_offsets=set()), str(cache_dir), str(errors))

    assert skipped == 0
    assert set(decoded) == {"L0"}


# ---------------------------------------------------------------------------
# main(): a bad --package (issue #49, mirrors #34's hzd_catalog check) must fail
# actionably, not with a raw FileNotFoundError traceback from hzd_locators. The
# check must run before any of the (possibly-missing) --manifest/--catalog/
# --clip-index files are opened, so this needs none of them to exist.
# ---------------------------------------------------------------------------

def test_render_main_missing_package_fails_actionably(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    bad_package = tmp_path / "install_root"  # exists, but no PackFileLocators.bin
    bad_package.mkdir()

    rc = render.main(["--package", str(bad_package)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "--hzd-package" in captured.out
    assert "PackFileLocators.bin" in captured.out
    assert captured.err == ""  # no traceback
