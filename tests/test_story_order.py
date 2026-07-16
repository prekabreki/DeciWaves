import csv

from deciwaves.games.ds import story_order as so
from deciwaves.games.ds import episode_map as em
from conftest import catalog_row as _row


def _crow(scene, stream, status="resolved", ti="0"):
    return dict(scene=scene, status=status, track_index=ti, voice_track_stream=stream)


def test_in_scope_filters():
    assert so.in_scope("npc", "lines_amelie")
    assert not so.in_scope("npc", "lines_mule01")
    assert so.in_scope("common", "lines_radio_nxt")
    assert not so.in_scope("common", "lines_catalog")
    assert not so.in_scope("sam", "lines_sam")


def test_subtitle_required():
    segs, _ = so.build_playlist([_row(subtitle_en=""), _row(subtitle_en="  ")], [], {})
    assert segs == []


def test_placeholder_none_subtitle_dropped():
    # "(none)" is a Decima placeholder (null voice, empty wem), not real dialogue.
    segs, _ = so.build_playlist(
        [_row(subtitle_en="(none)", wem_path_en="", speaker_code="localized/voices/vr0000_null")],
        [], {})
    assert segs == []


def test_empty_wem_path_yields_no_degenerate_stream():
    # A per-line row with a real subtitle but no wem path must not emit ".core.stream".
    segs, _ = so.build_playlist([_row(subtitle_en="A real line.", wem_path_en="")], [], {})
    assert segs == []


def test_within_scene_dedup_keeps_first():
    rows = [_row(line_index="0", subtitle_en="Sam."), _row(line_index="1", subtitle_en="Sam.")]
    segs, dropped = so.build_playlist(rows, [], {})
    assert len(segs) == 1 and segs[0].line_index == 0 and len(dropped) == 1


def test_cross_scene_repeat_kept():
    rows = [_row(scene="lines_pr201", subtitle_en="Sam."), _row(scene="lines_pr202", subtitle_en="Sam.")]
    segs, dropped = so.build_playlist(rows, [], {})
    assert len(segs) == 2 and dropped == []


def test_cutscene_per_line_rows_produce_no_segments():
    rows = [_row(category="cutscene", scene="sq_cs00_s00100", subtitle_en="A long cutscene line.")]
    segs, _ = so.build_playlist(rows, [], {})
    assert [s for s in segs if s.category == "cutscene"] == []


def test_cutscene_segments_from_tracks():
    crows = [_crow("sq_cs00_s00100", "a/b_voice_track.english.core.stream")]
    segs, _ = so.build_playlist([], crows, {})
    cs = [s for s in segs if s.category == "cutscene"]
    assert len(cs) == 1 and cs[0].stream_path == "a/b_voice_track.english.core.stream"
    assert cs[0].episode == 0


def test_unresolved_cutscene_track_skipped():
    segs, _ = so.build_playlist([], [_crow("sq_cs00_s00100", "", status="no_stream", ti="")], {})
    assert segs == []


def test_line_stream_path_appends_core_stream():
    segs, _ = so.build_playlist([_row(wem_path_en="loc/x.wem.english")], [], {})
    assert segs[0].stream_path == "loc/x.wem.english.core.stream"


def test_order_cutscene_groups_uses_anchor_then_hint():
    # cs53 anchored between cs03 and cs04; cs11 unanchored -> hint puts it last
    anchors = {"cs03": 400.0, "cs53": 460.0, "cs04": 600.0, "cs11": None}
    assert so.order_cutscene_groups(anchors) == ["cs03", "cs53", "cs04", "cs11"]


def test_order_cutscene_groups_default_fallback_orders_by_cs_number():
    # No transcript (the shipped default): every group is unanchored. Unhinted groups
    # must fall back to the numeric cs-number embedded in their name (not the old flat
    # tied sentinel), so the main story orders numerically and lands BEFORE the hinted
    # extras' explicit ~980+ keys. A group name with no parsable cs-number sorts last.
    groups = {"cs10": None, "cs2": None, "cs7": None, "cs71": None, "weird_group": None}
    assert so.order_cutscene_groups(groups) == ["cs2", "cs7", "cs10", "cs71", "weird_group"]


def test_order_cutscene_groups_hint_beats_cs_number(monkeypatch):
    # cs71's real CS_ORDER_HINT (980.0) already sorts after every low cs-number, so a mix
    # using it can't tell whether the `elif g in em.CS_ORDER_HINT` branch actually fired --
    # it would pass just from cs_number(71) alone. Monkeypatch a synthetic hint onto a
    # group whose raw cs-number (5) would otherwise sort it AMONG the main story, and
    # confirm the hint (990.0) wins instead, pushing it to the tail. This fails if the
    # `elif g in em.CS_ORDER_HINT` branch is removed (cs05 would fall through to
    # cs_number(cs05) == 5 and land between cs02 and cs09).
    monkeypatch.setitem(em.CS_ORDER_HINT, "cs05", 990.0)
    groups = {"cs02": None, "cs05": None, "cs09": None, "weird_group": None}
    assert so.order_cutscene_groups(groups) == ["cs02", "cs09", "cs05", "weird_group"]


def test_order_cutscene_groups_is_independent_of_input_order():
    # Same groups, deliberately different insertion/iteration order (standing in for the
    # hash-randomized set the caller used to build this from) -- output must not change.
    order_a = {"cs2": None, "cs10": None, "cs7": None, "weird_b": None, "weird_a": None}
    order_b = {"weird_a": None, "weird_b": None, "cs7": None, "cs10": None, "cs2": None}
    assert so.order_cutscene_groups(order_a) == so.order_cutscene_groups(order_b)
    # tied (unparseable) names must still resolve deterministically via the name tiebreak
    assert so.order_cutscene_groups(order_a)[-2:] == ["weird_a", "weird_b"]
    # and a set (genuinely hash-order-dependent iteration) feeds through the same way
    from_set = {g: None for g in {"cs2", "cs10", "cs7"}}
    assert so.order_cutscene_groups(from_set) == ["cs2", "cs7", "cs10"]


def test_cutscene_scenes_ordered_by_anchor_not_csnumber():
    # build an index so cs53 lines anchor between cs03 and cs04
    idx = {"line for cs03 scene here": 100, "line for cs53 scene here": 150,
           "line for cs04 scene here": 200}
    crows = [_crow("sq_cs03_s0", "s3.stream"), _crow("sq_cs53_s0", "s53.stream"),
             _crow("sq_cs04_s0", "s4.stream")]
    catalog = [
        _row(category="cutscene", scene="sq_cs03_s0", subtitle_en="Line for cs03 scene here"),
        _row(category="cutscene", scene="sq_cs53_s0", subtitle_en="Line for cs53 scene here"),
        _row(category="cutscene", scene="sq_cs04_s0", subtitle_en="Line for cs04 scene here"),
    ]
    segs, _ = so.build_playlist(catalog, crows, idx)
    order = [s.scene for s in segs if s.category == "cutscene"]
    assert order == ["sq_cs03_s0", "sq_cs53_s0", "sq_cs04_s0"]
    assert [s.episode for s in segs if s.scene == "sq_cs53_s0"][0] == 1  # rank 1 of 3


def test_side_sections_follow_spine_within_episode():
    crows = [_crow("sq_cs00_s00100", "cs.stream")]
    rows = [_row(category="mission", scene="lines_m00010", subtitle_en="A mission spine line."),
            _row(category="terminal", scene="lines_city_0w_101", subtitle_en="A terminal side line.")]
    segs, _ = so.build_playlist(rows, crows, {})
    # episode 0 only; spine (is_side=0) before side (is_side=1)
    flags = [s.is_side for s in segs]
    assert flags == sorted(flags)
    assert segs[-1].category == "terminal"


def test_npc_sorts_before_radio_within_episode():
    crows = [_crow("sq_cs00_s00100", "cs.stream")]  # establishes episode 0
    rows = [
        _row(category="common", scene="lines_radio_nxt", subtitle_en="A radio briefing line here."),
        _row(category="npc", scene="lines_deadman", subtitle_en="An npc character line here."),
    ]
    segs, _ = so.build_playlist(rows, crows, {})
    sides = [s.category for s in segs if s.is_side == 1]
    assert sides.index("npc") < sides.index("common")


def test_build_playlist_without_transcript_anchoring(tmp_path):
    # same synthetic catalog/cutscene fixtures as the existing happy-path tests,
    # but transcript disabled: ordering falls back to episode/scene order and no crash
    cat = tmp_path / "catalog.csv"
    with open(cat, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "core_path", "line_index", "category",
                                          "scene", "speaker_code", "speaker_name",
                                          "subtitle_en", "wem_path_en", "language"])
        w.writeheader()
        w.writerow(_row())

    tracks = tmp_path / "cutscene_tracks.csv"
    with open(tracks, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scene", "status", "track_index", "voice_track_stream"])
        w.writeheader()
        w.writerow(_crow("sq_cs00_s00100", "a/b_voice_track.english.core.stream"))

    out = tmp_path / "playlist.csv"
    rc = so.main(["--catalog", str(cat), "--cutscene-tracks", str(tracks),
                 "--out", str(out), "--transcript", ""])
    assert rc == 0 and out.exists()


def test_stale_dupes_file_removed_on_clean_rerun(tmp_path):
    """A prior run's render-dupes.csv (from back when there WERE dupes) must not
    linger and look current after a later, clean re-run that drops zero dupes --
    the dupes file is only ever written when `dropped` is non-empty, so a stale
    file must be actively removed, not silently left in place."""
    cat = tmp_path / "catalog.csv"
    with open(cat, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "core_path", "line_index", "category",
                                          "scene", "speaker_code", "speaker_name",
                                          "subtitle_en", "wem_path_en", "language"])
        w.writeheader()
        w.writerow(_row())   # a single row -> nothing to dedup, zero dupes

    tracks = tmp_path / "cutscene_tracks.csv"
    with open(tracks, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scene", "status", "track_index", "voice_track_stream"])
        w.writeheader()
        w.writerow(_crow("sq_cs00_s00100", "a/b_voice_track.english.core.stream"))

    out = tmp_path / "playlist.csv"
    dupes = tmp_path / "render-dupes.csv"
    dupes.write_text("line_id\nstale-from-a-previous-run\n", encoding="utf-8")

    rc = so.main(["--catalog", str(cat), "--cutscene-tracks", str(tracks),
                 "--out", str(out), "--transcript", "", "--dupes", str(dupes)])

    assert rc == 0
    assert not dupes.exists(), "stale dupes file must not survive a clean (zero-dupe) re-run"


def test_playlist_round_trip(tmp_path):
    segs = [so.Segment(0, 0, 12.5, 0, "sq_cs00_s00100", 0, 0, "cutscene", "(scene)", "",
                       "a.core.stream", "x#track0")]
    p = tmp_path / "pl.csv"
    so.write_playlist(segs, str(p))
    assert so.read_playlist(str(p)) == segs
