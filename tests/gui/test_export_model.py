"""Qt-free export model (#72, spec §8). Base .[test] install: NO importorskip -- this
module never imports PySide6 (mirrors test_library_model / test_preview_model).

Covers the three export building blocks: the filtered render-selection.csv writer (exactly
the checked rows, columns unchanged, BOM-FREE utf-8 so the DS/HZD render readers don't choke
-- the #84 bug class), the standalone-render argv builder (required install flags pulled from
config; FW --tiers covers every tier present so no checked row is dropped; no --main-story /
--spine-only), and the catalog source resolver.
"""
import csv
import glob
import os

from deciwaves.cli.config import resolve_ds_install
from deciwaves.gui.cli_command import default_base
from deciwaves.gui.export_model import (
    ExportError,
    can_export_mp3,
    catalog_source_path,
    render_selection_argv,
    write_render_selection,
    write_render_selection_with_tiers,
)

from deciwaves.games.ds import story_order
from deciwaves.games.ds.story_order import PLAYLIST_COLUMNS
from deciwaves.games.fw.manifest import MANIFEST_COLS as FW_COLS
from deciwaves.games.hzd.asr_bind import MANIFEST_COLS as HZD_COLS

BOM = b"\xef\xbb\xbf"


# --- fixture builders (real per-game schemas) ------------------------------

def _write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _ds_row(line_id, **kw):
    base = dict(episode="0", is_side="0", pos="0.0", section="0", scene="sq_cs01_s01",
                line_index="0", track_index="0", category="cutscene", speaker="Sam",
                subtitle="Hello.", stream_path=f"loc/{line_id}.wem.english.core.stream",
                line_id=line_id)
    base.update(kw)
    return base


def _hzd_row(line_id, **kw):
    base = dict(clip_row="1", offset="0", line_id=line_id, speaker_name="Aloy",
                subtitle_en="Hello.", scene="mq01", tier="1", score="0.9", transcript="hello")
    base.update(kw)
    return base


def _fw_row(line_id, tier="1", **kw):
    base = dict(line_id=line_id, wav=f"audio/{line_id}.wav", speaker="Aloy",
                subtitle="Hello.", gamescript_index="0", quest="q1", tier=tier,
                score="0.9", transcript="hello")
    base.update(kw)
    return base


def _make_ds_playlist(ws, ids):
    _write_csv(os.path.join(ws, "out", "playlist.csv"), PLAYLIST_COLUMNS,
               [_ds_row(i) for i in ids])


def _make_hzd_manifest(ws, ids):
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_COLS,
               [_hzd_row(i) for i in ids])


# --- write_render_selection ------------------------------------------------

def test_ds_writes_exactly_checked_rows_and_is_bom_free(tmp_path):
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a", "b", "c"])

    out = write_render_selection(ws, "ds", unchecked={"b"})

    assert out == os.path.join(ws, "out", "ds", "gui", "render-selection.csv")
    # BOM-free bytes: a fused BOM would KeyError the first column in read_playlist (#84).
    raw = open(out, "rb").read()
    assert not raw.startswith(BOM)
    # DS's own (BOM-intolerant, utf-8) reader parses it without KeyError.
    segs = story_order.read_playlist(out)
    assert [s.line_id for s in segs] == ["a", "c"]
    # header + column order preserved unchanged.
    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == PLAYLIST_COLUMNS


def test_ds_all_checked_keeps_every_row(tmp_path):
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a", "b", "c"])
    out = write_render_selection(ws, "ds", unchecked=set())
    assert [s.line_id for s in story_order.read_playlist(out)] == ["a", "b", "c"]


def test_hzd_filters_and_is_bom_free(tmp_path):
    ws = str(tmp_path)
    _make_hzd_manifest(ws, ["x", "y", "z"])
    out = write_render_selection(ws, "hzd", unchecked={"x", "z"})
    assert out == os.path.join(ws, "out", "hzd", "gui", "render-selection.csv")
    assert not open(out, "rb").read().startswith(BOM)
    with open(out, newline="", encoding="utf-8") as f:   # utf-8 (BOM-intolerant), like hzd render
        reader = csv.DictReader(f)
        assert reader.fieldnames == HZD_COLS
        assert [r["line_id"] for r in reader] == ["y"]


def test_fw_prefers_full_reel_over_subtitle_manifest(tmp_path):
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS,
               [_fw_row("full1"), _fw_row("full2")])
    _write_csv(os.path.join(root, "subtitle-manifest-full.csv"), FW_COLS,
               [_fw_row("sub1")])
    out = write_render_selection(ws, "fw", unchecked=set())
    with open(out, newline="", encoding="utf-8") as f:
        assert [r["line_id"] for r in csv.DictReader(f)] == ["full1", "full2"]


def test_fw_falls_back_to_subtitle_manifest(tmp_path):
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "subtitle-manifest-full.csv"), FW_COLS,
               [_fw_row("sub1"), _fw_row("sub2")])
    out = write_render_selection(ws, "fw", unchecked={"sub2"})
    with open(out, newline="", encoding="utf-8") as f:
        assert [r["line_id"] for r in csv.DictReader(f)] == ["sub1"]


def test_missing_source_raises_export_error(tmp_path):
    for game in ("ds", "hzd", "fw"):
        try:
            write_render_selection(str(tmp_path), game, unchecked=set())
        except ExportError:
            pass
        else:
            raise AssertionError(f"{game}: expected ExportError for missing render input")


def test_write_is_atomic_no_temp_left(tmp_path):
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a", "b"])
    write_render_selection(ws, "ds", unchecked=set())
    gui_dir = os.path.join(ws, "out", "ds", "gui")
    assert glob.glob(os.path.join(gui_dir, "render-selection.tmp.*")) == []


def test_source_bom_is_stripped_on_rewrite(tmp_path):
    # A source manifest saved with a UTF-8 BOM (PowerShell 5.1's utf8) must still yield a
    # BOM-free selection -- read utf-8-sig, write plain utf-8.
    ws = str(tmp_path)
    path = os.path.join(ws, "out", "hzd", "asr-manifest.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # writes a BOM
        w = csv.DictWriter(f, fieldnames=HZD_COLS)
        w.writeheader()
        w.writerow(_hzd_row("y"))
    assert open(path, "rb").read().startswith(BOM)   # sanity: source really has a BOM
    out = write_render_selection(ws, "hzd", unchecked=set())
    assert not open(out, "rb").read().startswith(BOM)
    with open(out, newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == HZD_COLS   # not "﻿clip_row"


# --- can_export_mp3 --------------------------------------------------------

def test_can_export_mp3_reflects_render_input_presence(tmp_path):
    ws = str(tmp_path)
    assert can_export_mp3(ws, "ds") is False
    _make_ds_playlist(ws, ["a"])
    assert can_export_mp3(ws, "ds") is True

    assert can_export_mp3(ws, "hzd") is False
    _make_hzd_manifest(ws, ["x"])
    assert can_export_mp3(ws, "hzd") is True

    assert can_export_mp3(ws, "fw") is False
    _write_csv(os.path.join(ws, "out", "fw", "subtitle-manifest-full.csv"), FW_COLS,
               [_fw_row("s")])
    assert can_export_mp3(ws, "fw") is True


# --- render_selection_argv (validated against the REAL render argparse) -----

def _stage_tokens(argv):
    """The render stage's own args -- everything after the single 'render' stage token."""
    return argv[argv.index("render") + 1:]


def test_ds_argv_carries_required_install_flags_and_bitrate(tmp_path, parsed_stage_args):
    from deciwaves.engine import render as ds_render
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a"])
    csv_path = write_render_selection(ws, "ds", unchecked=set())
    cfg = {"ds_install": r"C:\DS"}
    argv = render_selection_argv(default_base(), ws, "ds", csv_path, bitrate=192, cfg=cfg)

    assert "--main-story" not in argv     # render exactly the checked rows, no spine cull
    ns = parsed_stage_args(ds_render.main, _stage_tokens(argv))
    assert ns.playlist == os.path.abspath(csv_path)
    assert ns.data_dir == os.path.join(r"C:\DS", "data")
    assert ns.oodle == os.path.join(r"C:\DS", "oo2core_7_win64.dll")
    assert ns.bitrate == 192
    assert ns.main_story is False


def test_ds_argv_uses_explicit_oodle_dll_override(tmp_path, parsed_stage_args):
    from deciwaves.engine import render as ds_render
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a"])
    csv_path = write_render_selection(ws, "ds", unchecked=set())
    cfg = {"ds_install": r"C:\DS", "oodle_dll": r"C:\custom\oo.dll"}
    argv = render_selection_argv(default_base(), ws, "ds", csv_path, bitrate=128, cfg=cfg)
    ns = parsed_stage_args(ds_render.main, _stage_tokens(argv))
    assert ns.oodle == r"C:\custom\oo.dll"


def test_ds_argv_unconfigured_install_raises(tmp_path):
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a"])
    csv_path = write_render_selection(ws, "ds", unchecked=set())
    try:
        render_selection_argv(default_base(), ws, "ds", csv_path, bitrate=128, cfg={})
    except ExportError:
        return
    raise AssertionError("expected ExportError when DS install is unconfigured")


def test_hzd_argv_requires_package_no_spine_only(tmp_path, parsed_stage_args):
    from deciwaves.games.hzd import render as hzd_render
    ws = str(tmp_path)
    _make_hzd_manifest(ws, ["x"])
    csv_path = write_render_selection(ws, "hzd", unchecked=set())
    argv = render_selection_argv(default_base(), ws, "hzd", csv_path, bitrate=128,
                                 cfg={"hzd_package": "PKG"})
    assert "--spine-only" not in argv     # keep every checked row, not just the mq spine
    ns = parsed_stage_args(hzd_render.main, _stage_tokens(argv))
    assert ns.manifest == os.path.abspath(csv_path)
    assert ns.package == "PKG"
    assert ns.spine_only is False


def test_hzd_argv_unconfigured_package_raises(tmp_path):
    ws = str(tmp_path)
    _make_hzd_manifest(ws, ["x"])
    csv_path = write_render_selection(ws, "hzd", unchecked=set())
    try:
        render_selection_argv(default_base(), ws, "hzd", csv_path, bitrate=128, cfg={})
    except ExportError:
        return
    raise AssertionError("expected ExportError when HZD package is unconfigured")


def test_fw_argv_tiers_cover_every_tier_present(tmp_path, parsed_stage_args):
    from deciwaves.games.fw import render as fw_render
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    # a mix of tiers among the checked rows -- ALL must survive the --tiers filter.
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS, [
        _fw_row("a", tier="1"), _fw_row("b", tier="2"),
        _fw_row("c", tier="S"), _fw_row("d", tier="W"), _fw_row("e", tier="D"),
    ])
    csv_path = write_render_selection(ws, "fw", unchecked=set())
    argv = render_selection_argv(default_base(), ws, "fw", csv_path, bitrate=128, cfg={})
    assert "--spine-only" not in argv and "--main-story" not in argv

    ns = parsed_stage_args(fw_render.main, _stage_tokens(argv))
    assert ns.manifest == os.path.abspath(csv_path)
    assert ns.uniform_mono is True
    # the invariant: build_spine keeps only tiers in --tiers; every present tier must be in it.
    passed_tiers = {t.strip() for t in ns.tiers.split(",") if t.strip()}
    assert passed_tiers == {"1", "2", "S", "W", "D"}
    kept = fw_render.build_spine(
        [_fw_row("a", tier="1", gamescript_index="0"),
         _fw_row("b", tier="2", gamescript_index="1"),
         _fw_row("c", tier="S", gamescript_index="2"),
         _fw_row("d", tier="W", gamescript_index="3"),
         _fw_row("e", tier="D", gamescript_index="4")],
        bound_tiers=passed_tiers)
    assert {i.line_id for i in kept} == {"a", "b", "c", "d", "e"}   # nothing tier-dropped


# --- render_selection_argv scope kwargs (#73, backward-compatible) ---------

def test_ds_main_story_kwarg_appends_flag(tmp_path, parsed_stage_args):
    from deciwaves.engine import render as ds_render
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a"])
    csv_path = write_render_selection(ws, "ds", unchecked=set())
    cfg = {"ds_install": r"C:\DS"}
    argv = render_selection_argv(default_base(), ws, "ds", csv_path, bitrate=128, cfg=cfg,
                                 main_story=True)
    assert "--main-story" in argv
    ns = parsed_stage_args(ds_render.main, _stage_tokens(argv))
    assert ns.main_story is True
    # regression guard: the default (no kwarg) still omits it -- #72's contract.
    unscoped = render_selection_argv(default_base(), ws, "ds", csv_path, bitrate=128, cfg=cfg)
    assert "--main-story" not in unscoped


def test_hzd_spine_only_kwarg_appends_flag(tmp_path, parsed_stage_args):
    from deciwaves.games.hzd import render as hzd_render
    ws = str(tmp_path)
    _make_hzd_manifest(ws, ["x"])
    csv_path = write_render_selection(ws, "hzd", unchecked=set())
    cfg = {"hzd_package": "PKG"}
    argv = render_selection_argv(default_base(), ws, "hzd", csv_path, bitrate=128, cfg=cfg,
                                 spine_only=True)
    assert "--spine-only" in argv
    ns = parsed_stage_args(hzd_render.main, _stage_tokens(argv))
    assert ns.spine_only is True
    unscoped = render_selection_argv(default_base(), ws, "hzd", csv_path, bitrate=128, cfg=cfg)
    assert "--spine-only" not in unscoped


def test_fw_default_tiers_keep_w_and_d_rows(tmp_path, parsed_stage_args):
    """Regression lock (#72/#106): default --tiers preserves every present tier
    (W and D specifically) so no checked row is dropped."""
    from deciwaves.games.fw import render as fw_render
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS, [
        _fw_row("wav1", tier="W"), _fw_row("wav2", tier="D"),
    ])
    csv_path = write_render_selection(ws, "fw", unchecked=set())
    argv = render_selection_argv(default_base(), ws, "fw", csv_path, bitrate=128, cfg={})
    ns = parsed_stage_args(fw_render.main, _stage_tokens(argv))
    passed_tiers = {t.strip() for t in ns.tiers.split(",") if t.strip()}
    assert passed_tiers == {"W", "D"}
    kept = fw_render.build_spine(
        [_fw_row("wav1", tier="W", gamescript_index="0"),
         _fw_row("wav2", tier="D", gamescript_index="1")],
        bound_tiers=passed_tiers)
    assert {i.line_id for i in kept} == {"wav1", "wav2"}


def test_fw_explicit_tiers_replace_union_and_can_drop_a_row(tmp_path, parsed_stage_args):
    from deciwaves.games.fw import render as fw_render
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS, [
        _fw_row("a", tier="1"), _fw_row("w", tier="W"),
    ])
    csv_path = write_render_selection(ws, "fw", unchecked=set())
    # explicit tiers REPLACE the present-tier union -- the W row is intentionally dropped.
    argv = render_selection_argv(default_base(), ws, "fw", csv_path, bitrate=128, cfg={},
                                 tiers="1,2,S")
    ns = parsed_stage_args(fw_render.main, _stage_tokens(argv))
    assert ns.tiers == "1,2,S"
    kept = fw_render.build_spine(
        [_fw_row("a", tier="1", gamescript_index="0"),
         _fw_row("w", tier="W", gamescript_index="1")],
        bound_tiers={"1", "2", "S"})
    assert {i.line_id for i in kept} == {"a"}   # the W-tier row is scope-narrowed out
    # regression guard: with no explicit tiers, the union covers every present tier (#72).
    unscoped = render_selection_argv(default_base(), ws, "fw", csv_path, bitrate=128, cfg={})
    ns2 = parsed_stage_args(fw_render.main, _stage_tokens(unscoped))
    assert {t.strip() for t in ns2.tiers.split(",")} == {"1", "W"}


# --- catalog_source_path ---------------------------------------------------

def test_catalog_source_ds_and_hzd(tmp_path):
    ws = str(tmp_path)
    assert catalog_source_path(ws, "ds") is None
    open_dir = os.path.join(ws, "out")
    os.makedirs(open_dir, exist_ok=True)
    open(os.path.join(open_dir, "catalog.csv"), "w").close()
    assert catalog_source_path(ws, "ds") == os.path.join(ws, "out", "catalog.csv")

    hzd_dir = os.path.join(ws, "out", "hzd")
    os.makedirs(hzd_dir, exist_ok=True)
    open(os.path.join(hzd_dir, "catalog.csv"), "w").close()
    assert catalog_source_path(ws, "hzd") == os.path.join(hzd_dir, "catalog.csv")


def test_catalog_source_fw_uses_clip_index(tmp_path):
    ws = str(tmp_path)
    assert catalog_source_path(ws, "fw") is None   # FW has no catalog
    fw_dir = os.path.join(ws, "out", "fw")
    os.makedirs(fw_dir, exist_ok=True)
    open(os.path.join(fw_dir, "clip-index.csv"), "w").close()
    assert catalog_source_path(ws, "fw") == os.path.join(fw_dir, "clip-index.csv")


# --- resolve_ds_install: shared helper matches CLI's resolution ------------

def test_resolve_ds_install_matches_cli():
    """The shared helper produces the same (data_dir, oodle) that the CLI's
    own code path does for a given config (regression guard: the helper and
    CLI must agree so preview/export don't silently resolve differently)."""
    cfg = {"ds_install": r"C:\DS"}
    data_dir, oodle = resolve_ds_install(cfg)
    assert data_dir == r"C:\DS\data"
    assert oodle == r"C:\DS\oo2core_7_win64.dll"

    cfg_override = {"ds_install": r"C:\DS", "oodle_dll": r"D:\oo.dll"}
    data_dir2, oodle2 = resolve_ds_install(cfg_override)
    assert data_dir2 == r"C:\DS\data"
    assert oodle2 == r"D:\oo.dll"

    # Unconfigured -> (None, None)
    assert resolve_ds_install({}) == (None, None)


# --- write_render_selection_with_tiers (M8a) -------------------------------

def test_write_render_selection_with_tiers_returns_fw_tiers(tmp_path):
    """The tier union is computed during the single write pass and returned
    correctly — no re-read of the just-written file (M8a)."""
    from deciwaves.games.fw import render as fw_render
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS, [
        _fw_row("a", tier="1"), _fw_row("b", tier="W"),
        _fw_row("c", tier="1"),  # duplicate tier — only first-seen counts
    ])

    csv_path, fw_tiers = write_render_selection_with_tiers(ws, "fw", unchecked={"b"})
    assert os.path.isfile(csv_path)
    assert fw_tiers == "1"  # row "b" (tier=W) was unchecked, so union is just {"1"}

    # Verify the tier union is correct for the checked rows
    passed = {t.strip() for t in fw_tiers.split(",") if t.strip()}
    kept = fw_render.build_spine(
        [_fw_row("a", tier="1", gamescript_index="0"),
         _fw_row("c", tier="1", gamescript_index="1")],
        bound_tiers=passed)
    assert {i.line_id for i in kept} == {"a", "c"}


def test_write_render_selection_with_tiers_all_checked_union(tmp_path):
    ws = str(tmp_path)
    root = os.path.join(ws, "out", "fw")
    _write_csv(os.path.join(root, "full-reel-manifest.csv"), FW_COLS, [
        _fw_row("a", tier="1"), _fw_row("b", tier="2"),
        _fw_row("c", tier="S"),
    ])
    csv_path, fw_tiers = write_render_selection_with_tiers(ws, "fw", unchecked=set())
    assert fw_tiers == "1,2,S"


def test_write_render_selection_with_tiers_non_fw_returns_empty_tiers(tmp_path):
    ws = str(tmp_path)
    _make_ds_playlist(ws, ["a"])
    csv_path, fw_tiers = write_render_selection_with_tiers(ws, "ds", unchecked=set())
    assert fw_tiers == ""
    assert os.path.isfile(csv_path)
