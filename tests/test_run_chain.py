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
