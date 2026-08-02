from deciwaves.engine.render_spine import BOUND_TIERS, REQUIRED_COLS, RenderItem, build_spine


def _row(line_id, gidx, quest, tier="1", speaker="Aloy", subtitle="x", wav=None):
    return {"line_id": line_id, "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "speaker": speaker, "subtitle": subtitle,
            "wav": wav or f"audio/{line_id}.wav"}


def test_tier_filter_drops_out_of_tier_row():
    rows = [_row("c0", 1, "Q1", tier="1"),
            _row("c1", 2, "Q1", tier="3"),
            _row("c2", 3, "Q1", tier="2")]
    spine = build_spine(rows)
    assert [s.line_id for s in spine] == ["c0", "c2"]


def test_rows_sort_by_gamescript_index():
    rows = [_row("c2", 5, "Q1"), _row("c0", 1, "Q1"), _row("c1", 3, "Q1")]
    spine = build_spine(rows)
    assert [s.line_id for s in spine] == ["c0", "c1", "c2"]
    assert [s.gamescript_index for s in spine] == [1, 3, 5]


def test_distinct_quests_get_dense_episode_in_gamescript_order():
    rows = [_row("c0", 1, "Q1"), _row("c1", 2, "Q2"),
            _row("c2", 3, "Q3"), _row("c3", 4, "Q2")]
    spine = build_spine(rows)
    assert [s.episode for s in spine] == [0, 1, 2, 1]
    assert [s.quest for s in spine] == ["Q1", "Q2", "Q3", "Q2"]


def test_default_bound_tiers_match_required_spine():
    assert BOUND_TIERS == {"1", "2", "S"}
    assert "line_id" in REQUIRED_COLS
    assert "gamescript_index" in REQUIRED_COLS
    assert "tier" in REQUIRED_COLS
    assert isinstance(build_spine([_row("c0", 1, "Q1")])[0], RenderItem)
