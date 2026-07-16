from deciwaves.cli import run as run_mod
from deciwaves.games.fw import render, story_full


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


# ---------------------------------------------------------------------------
# CLI defaults (issue #17): a manual `deciwaves fw render` (no flags) must be
# usable on its own, not just as the tail of `fw run`'s hand-wired chain.
# ---------------------------------------------------------------------------

def test_render_default_manifest_matches_full_reel_stage_output(parsed_stage_args):
    """render's own --manifest default must be the file the full-reel stage
    (story_full.py) actually writes by default, not the dead bind.py flow's
    out/fw/asr-manifest.csv that nothing produces anymore."""
    render_ns = parsed_stage_args(render.main, [])
    full_reel_ns = parsed_stage_args(story_full.main, [])
    assert render_ns.manifest == full_reel_ns.out


def test_render_default_tiers_ships_the_subtitle_tier(parsed_stage_args):
    """Default --tiers must include "S" -- most of the full reel is tier-S
    subtitle-only lines; silently dropping them defeats the point of the
    full-reel manifest."""
    ns = parsed_stage_args(render.main, [])
    tiers = {t.strip() for t in ns.tiers.split(",") if t.strip()}
    assert tiers == {"1", "2", "S"}


def test_render_defaults_are_in_lockstep_with_fw_run_wiring(parsed_stage_args):
    """`deciwaves fw run`'s render stage must resolve to the SAME
    manifest/tiers as a bare `deciwaves fw render` -- compared directly
    (not two hardcoded literals that merely happen to match today), so a
    future edit to either side alone fails this test instead of silently
    drifting (issue #17)."""
    bare = parsed_stage_args(render.main, [])
    wired = parsed_stage_args(render.main, run_mod._fw_render_argv({}))
    assert wired.manifest == bare.manifest
    assert wired.tiers == bare.tiers
