import csv

from deciwaves.cli import run as run_mod
from deciwaves.games.fw import render, story_full


def _row(line_id, gidx, quest, tier="1", speaker="Aloy", subtitle="x", wav=None):
    return {"line_id": line_id, "gamescript_index": str(gidx), "quest": quest,
            "tier": tier, "speaker": speaker, "subtitle": subtitle,
            "wav": wav or f"audio/{line_id}.wav"}


def _write_manifest(path, rows):
    cols = ["line_id", "gamescript_index", "quest", "tier", "speaker", "subtitle", "wav"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


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


# ---------------------------------------------------------------------------
# main(): empty-render guard (issue #64). Only DS render refused to proceed
# when nothing decoded; FW discarded its measure-fail count and ignored
# assemble_reels' return value, so a render producing ZERO output exited 0.
# ---------------------------------------------------------------------------

def _render_argv(tmp_path, manifest, **extra):
    argv = ["--manifest", str(manifest),
            "--audio-root", str(tmp_path),
            "--out-dir", str(tmp_path / "reels"),
            "--cache", str(tmp_path / "cache"),
            "--errors", str(tmp_path / "render-errors.log")]
    for k, v in extra.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return argv


def test_fw_render_main_missing_wavs_exits_nonzero_with_message(tmp_path, capsys):
    """THE acceptance test for #64: `fw render` against a manifest whose WAVs
    are missing must exit non-zero with a legible message (errors-log pointer,
    audio-root hint) -- not exit 0 having written zero reels."""
    manifest = tmp_path / "full-reel-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1"), _row("c1", 2, "Q1")])
    # no WAVs are created under --audio-root: every measure fails

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc != 0
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert str(tmp_path / "render-errors.log") in out
    assert "--audio-root" in out          # the actionable hint itself, not an echoed path
    assert "deciwaves fw extract" in out  # a RUNNABLE command (issue #23 convention)
    assert not list((tmp_path / "reels").glob("*.mp3"))  # nothing was written


def test_fw_render_main_empty_spine_is_a_noop_success(tmp_path, capsys):
    """A selection that legitimately matches nothing (here: every row an
    unbound tier) is a NO-OP, not a failure -- DS's empty-playlist precedent
    (review of #64: `--tiers D`, endorsed by the flag's help, never matches
    the standard full-reel manifest since DLC ships via a separate manifest;
    failing would make a deliberate no-op indistinguishable from a broken
    pipeline). Still loud: the notice names the manifest and the filter, and
    it must fire BEFORE measure/assemble side effects (no errors.log
    truncation, no cache writes)."""
    manifest = tmp_path / "full-reel-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1", tier="3")])

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to render" in out
    assert "--tiers" in out
    assert not (tmp_path / "render-errors.log").exists()  # measure never ran
    assert not (tmp_path / "cache").exists()              # assemble never ran


def test_fw_render_main_empty_spine_drops_stale_errors_log(tmp_path, capsys):
    """A no-op must not leave a PRIOR run's render-errors.log on disk to be
    misread as this run's failures (review of #64): measure -- the only writer,
    which rewrites the log from scratch each run -- never runs on the no-op, so
    the no-op itself must drop a stale log to keep that contract."""
    manifest = tmp_path / "full-reel-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1", tier="3")])  # all unbound -> empty spine
    stale = tmp_path / "render-errors.log"
    stale.write_text("c9\tprior-run failure\n", encoding="utf-8")

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    assert not stale.exists()   # gone, not silently attributed to this no-op


def test_fw_render_main_empty_input_manifest_is_upstream_error(tmp_path, capsys):
    """A header-only manifest means an upstream stage produced nothing -- a
    broken/empty pipeline, NOT a deliberate selection. It must fail LOUD (rc 1)
    so `fw run`/the GUI stage strip can't show render green with zero audio
    end-to-end (issue #85; the empty-INPUT case #64/#63/#81 exist to kill). The
    message names the real cause -- zero rows, upstream -- not the --tiers
    filter a user could never fix by editing (kept from the review of #64)."""
    manifest = tmp_path / "full-reel-manifest.csv"
    _write_manifest(manifest, [])   # header only, 0 data rows

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "no rows" in out
    assert str(manifest) in out
    assert "--tiers" not in out    # don't misdirect to a filter that can't help
    assert not (tmp_path / "cache").exists()   # fired before assemble side effects


def test_fw_render_main_surfaces_partial_measure_failures(tmp_path, monkeypatch, capsys):
    """A PARTIAL measure failure stays fail-soft (render proceeds), but the
    count must be surfaced like DS/HZD do -- FW used to discard n_failed
    entirely."""
    import wave as wave_mod
    audio = tmp_path / "audio"
    audio.mkdir()
    with wave_mod.open(str(audio / "c0.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 4800)
    manifest = tmp_path / "full-reel-manifest.csv"
    _write_manifest(manifest, [_row("c0", 1, "Q1"), _row("c1", 2, "Q1")])  # c1.wav missing

    # assembly itself needs ffmpeg and isn't under test; pretend one reel was written
    monkeypatch.setattr(render, "assemble_reels", lambda *a, **k: 1)

    rc = render.main(_render_argv(tmp_path, manifest))

    assert rc == 0
    out = capsys.readouterr().out
    # the exact surfaced line, not a substring the always-printed header
    # already satisfies (review of #64: `"1" in out` was vacuously true)
    assert "measure: 1 clip(s) failed" in out
