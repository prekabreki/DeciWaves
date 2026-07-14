from deciwaves.games.fw import render


def _row(line_id, gidx, quest, tier="1", speaker="Aloy", subtitle="x", wav=None):
    return {"line_id": line_id, "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "speaker": speaker, "subtitle": subtitle,
            "wav": wav or f"audio/{line_id}.wav"}


def test_spine_orders_by_gamescript_index():
    rows = [_row("c2", 5, "Q1"), _row("c0", 1, "Q1"), _row("c1", 3, "Q1")]
    spine = render.build_spine(rows)
    assert [s.line_id for s in spine] == ["c0", "c1", "c2"]
    assert [s.gamescript_index for s in spine] == [1, 3, 5]


def test_spine_assigns_dense_episode_per_quest():
    rows = [_row("c0", 1, "Q1"), _row("c1", 2, "Q1"), _row("c2", 3, "Q2")]
    spine = render.build_spine(rows)
    assert [s.episode for s in spine] == [0, 0, 1]


def test_spine_excludes_unbound_tier3():
    rows = [_row("c0", 1, "Q1", tier="1"),
            _row("c1", 2, "Q1", tier="3"),
            _row("c2", 3, "Q1", tier="2")]
    spine = render.build_spine(rows)
    assert [s.line_id for s in spine] == ["c0", "c2"]


def test_spine_can_restrict_to_tier1():
    rows = [_row("c0", 1, "Q1", tier="1"), _row("c1", 2, "Q1", tier="2")]
    spine = render.build_spine(rows, bound_tiers={"1"})
    assert [s.line_id for s in spine] == ["c0"]
