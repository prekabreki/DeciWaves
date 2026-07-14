from deciwaves.engine import story_order as so


def _row(**kw):
    base = dict(line_id="id", core_path="c", line_index="0", category="terminal",
                scene="lines_pr201", speaker_code="", speaker_name="The Engineer",
                subtitle_en="Hello there friend.", wem_path_en="loc/x.wem.english",
                language="english")
    base.update(kw)
    return base


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


def test_playlist_round_trip(tmp_path):
    segs = [so.Segment(0, 0, 12.5, 0, "sq_cs00_s00100", 0, 0, "cutscene", "(scene)", "",
                       "a.core.stream", "x#track0")]
    p = tmp_path / "pl.csv"
    so.write_playlist(segs, str(p))
    assert so.read_playlist(str(p)) == segs
