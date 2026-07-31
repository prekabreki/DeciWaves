"""Unit tests for gui/artifact_paths.py -- the per-game artifact layout.

These two facts were previously duplicated across export_model / library_model /
progress_model, so the point of testing them here is that there is now exactly one place
where a wrong answer can come from.
"""

import os

from deciwaves.gui.artifact_paths import out_dir, pipeline_render_input


def test_out_dir_ds_is_out_root():
    """DS artifacts live in out/ ROOT, not out/ds/ (spec §9 gotcha #6)."""
    assert out_dir("/ws", "ds") == os.path.join("/ws", "out")


def test_out_dir_other_games_are_namespaced():
    assert out_dir("/ws", "hzd") == os.path.join("/ws", "out", "hzd")
    assert out_dir("/ws", "fw") == os.path.join("/ws", "out", "fw")


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("line_id\na\n")


def test_pipeline_render_input_none_before_the_stage_ran(tmp_path):
    ws = str(tmp_path)
    assert pipeline_render_input(ws, "ds") is None
    assert pipeline_render_input(ws, "hzd") is None
    assert pipeline_render_input(ws, "fw") is None


def test_pipeline_render_input_per_game(tmp_path):
    ws = str(tmp_path)
    _touch(os.path.join(ws, "out", "playlist.csv"))
    _touch(os.path.join(ws, "out", "hzd", "asr-manifest.csv"))
    assert pipeline_render_input(ws, "ds").endswith("playlist.csv")
    assert pipeline_render_input(ws, "hzd").endswith("asr-manifest.csv")


def test_pipeline_render_input_fw_prefers_full_reel(tmp_path):
    """FW has two candidates: the full-reel manifest wins over the subtitle-only one, which
    is what a user with types.json but no BYO gamescript gets from subtitle-bind."""
    ws = str(tmp_path)
    _touch(os.path.join(ws, "out", "fw", "subtitle-manifest-full.csv"))
    assert pipeline_render_input(ws, "fw").endswith("subtitle-manifest-full.csv")
    _touch(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"))
    assert pipeline_render_input(ws, "fw").endswith("full-reel-manifest.csv")


def test_pipeline_render_input_unknown_game_is_none(tmp_path):
    assert pipeline_render_input(str(tmp_path), "nope") is None
