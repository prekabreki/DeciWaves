"""`run.run_chain` is the single source of truth for each game's `run` stage chain --
the per-game runners execute it AND the GUI stage strip (#69) reads it, so it can't drift
from what `deciwaves <game> run` actually does. This pins the exact tokens + GPU flags."""
import pytest

from deciwaves.cli import run


def _names(game):
    return [s.name for s in run.run_chain(game)]


def test_ds_chain_tokens_and_no_gpu():
    chain = run.run_chain("ds")
    assert [s.name for s in chain] == ["catalog", "order", "render"]
    assert all(not s.gpu for s in chain)


def test_hzd_chain_tokens_and_bind_is_gpu():
    chain = run.run_chain("hzd")
    assert [s.name for s in chain] == ["catalog", "clip-index", "wem-metadata", "bind", "render"]
    assert {s.name for s in chain if s.gpu} == {"bind"}


def test_fw_chain_tokens_and_asr_is_gpu():
    chain = run.run_chain("fw")
    assert [s.name for s in chain] == [
        "extract", "asr", "subtitle-bind", "match", "full-reel", "render"]
    assert {s.name for s in chain if s.gpu} == {"asr"}


def test_unknown_game_raises():
    with pytest.raises(KeyError):
        run.run_chain("zzz")


def test_stage_names_roundtrip_through_coverage_sections(tmp_path):
    """Stage names from ``run.run_chain`` are exactly the coverage section
    names that ``_remove_marker`` passes to ``clear_stage_coverage`` (issue #91
    item 8).  A rename in ``run_chain`` that is not reflected in coverage would
    silently make invalidation a no-op -- this test pins the two name sets
    equal by roundtripping every stage name through write-then-clear."""
    from deciwaves.engine.coverage import (clear_stage_coverage,
                                            read_json_object,
                                            write_stage_coverage)
    for game in ("ds", "hzd", "fw"):
        path = str(tmp_path / game / "coverage.json")
        for stage in run.run_chain(game):
            write_stage_coverage(path, stage.name, {"dummy": 1})
            data = read_json_object(path)
            assert data[stage.name]["dummy"] == 1
        for stage in run.run_chain(game):
            clear_stage_coverage(path, stage.name)
            data = read_json_object(path)
            assert stage.name not in data
