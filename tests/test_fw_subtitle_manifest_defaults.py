"""Subtitle-manifest filename lockstep (issue #17).

`subtitle_bind.py` (the producer) and `subtitle_match.py` / `story_full.py` /
`weave.py` (the consumers) must all agree on ONE default subtitle-manifest
filename. Before the fix, the producer defaulted to
`out/fw/subtitle-manifest.csv` while every consumer defaulted to
`out/fw/subtitle-manifest-full.csv` -- a manual, unwired user hit
FileNotFoundError (or silently read a stale file); `cli/run.py` papered over
the mismatch with an explicit `--out` override plus an explanatory comment.

These tests compare the REAL argparse defaults each module resolves to
(via the `parsed_stage_args` fixture in conftest.py), not re-declared
literals, so a future edit that reintroduces divergence on either side fails
loudly here instead of drifting silently.
"""
from deciwaves.cli import run as run_mod
from deciwaves.games.fw import story_full, subtitle_bind, subtitle_match, weave


def test_subtitle_bind_default_out_matches_match_default_manifest(parsed_stage_args):
    producer = parsed_stage_args(subtitle_bind.main, ["--package-dir", "PKG"])
    consumer = parsed_stage_args(subtitle_match.main, [])
    assert producer.out == consumer.manifest


def test_subtitle_bind_default_out_matches_story_full_default_subtitles(parsed_stage_args):
    producer = parsed_stage_args(subtitle_bind.main, ["--package-dir", "PKG"])
    consumer = parsed_stage_args(story_full.main, [])
    assert producer.out == consumer.subtitles


def test_subtitle_bind_default_out_matches_weave_default_subtitles(parsed_stage_args):
    producer = parsed_stage_args(subtitle_bind.main, ["--package-dir", "PKG"])
    consumer = parsed_stage_args(weave.main, [])
    assert producer.out == consumer.subtitles


def test_subtitle_bind_defaults_are_in_lockstep_with_fw_run_wiring(parsed_stage_args):
    """`deciwaves fw run` must no longer need to override subtitle-bind's
    --out to bridge a filename mismatch -- its wired argv must resolve to
    the SAME --out as a bare `deciwaves fw subtitle-bind` (issue #17: the
    workaround comment + override in cli/run.py must be gone)."""
    bare = parsed_stage_args(subtitle_bind.main, ["--package-dir", "PKG"])
    wired = parsed_stage_args(
        subtitle_bind.main, run_mod._fw_subtitle_bind_argv({"package": "PKG"}))
    assert wired.out == bare.out
