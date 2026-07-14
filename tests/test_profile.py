"""Tests for engine.profile.GameProfile dataclass (Task 2.1).

TDD: written before the implementation exists. Run first → ImportError (RED).
After implementing engine/profile.py → all tests pass (GREEN).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]

from deciwaves.engine.profile import GameProfile  # noqa: E402
from deciwaves.games.ds.profile import DS_CORE_PREFIXES  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def _ds_prefixes() -> dict[str, str]:
    """Returns the authoritative DS prefix map from deciwaves.games.ds.profile."""
    return dict(DS_CORE_PREFIXES)


def _simpletext_filter(path: str) -> bool:
    """Mirrors the inline filter in speakers.py SpeakerMap.__init__."""
    return "sentences/voices/" in path and path.strip().endswith("/simpletext")


def _make_profile(**overrides) -> GameProfile:
    defaults: dict[str, Any] = dict(
        name="ds",
        pack_reader=MagicMock(),
        decima_version="DSPC",
        core_prefixes=_ds_prefixes(),
        speaker_simpletext_filter=_simpletext_filter,
        transcript_path="docs/death_stranding_gamescript.md",
        out_dir="out/ds",
    )
    defaults.update(overrides)
    return GameProfile(**defaults)


# ── construction tests ──────────────────────────────────────────────────────

def test_gameprofile_constructs_with_required_fields():
    """Basic construction succeeds; name and decima_version round-trip."""
    p = _make_profile()
    assert p.name == "ds"
    assert p.decima_version == "DSPC"


def test_gameprofile_core_prefixes_matches_ds_catalog():
    """core_prefixes maps all six DS prefix strings to their categories."""
    p = _make_profile()
    expected = _ds_prefixes()
    assert p.core_prefixes == expected


def test_gameprofile_speaker_simpletext_filter_matches_ds_speakers():
    """speaker_simpletext_filter mirrors the filter logic in speakers.py.

    speakers.py uses ``p.strip().endswith("/simpletext")``, so a trailing-space
    path still matches (stripped before the endswith check).  Non-simpletext
    voice paths are rejected.
    """
    p = _make_profile()
    f = p.speaker_simpletext_filter
    assert f("localized/sentences/voices/vr0010_sam/simpletext") is True
    assert f("localized/sentences/voices/vr0010_sam/simpletext ") is True   # strip() makes this match
    assert f("localized/voices/vr0010_sam") is False                        # no "sentences/voices/"
    assert f("localized/sentences/voices/vr0010_sam/metadata") is False     # wrong suffix


def test_gameprofile_paths():
    """transcript_path and out_dir are stored as given."""
    p = _make_profile()
    assert p.transcript_path == "docs/death_stranding_gamescript.md"
    assert p.out_dir == "out/ds"


def test_gameprofile_optional_fields_default_to_none():
    """episode_map and cutscene_resolver are optional and default to None."""
    p = _make_profile()
    assert p.episode_map is None
    assert p.cutscene_resolver is None


def test_gameprofile_optional_fields_accept_callables():
    """episode_map and cutscene_resolver accept callables when provided."""
    dummy_em = MagicMock()
    dummy_cr = MagicMock()
    p = _make_profile(episode_map=dummy_em, cutscene_resolver=dummy_cr)
    assert p.episode_map is dummy_em
    assert p.cutscene_resolver is dummy_cr


def test_gameprofile_is_frozen():
    """GameProfile is a frozen dataclass — mutation raises FrozenInstanceError."""
    import dataclasses
    p = _make_profile()
    try:
        p.name = "hzd"  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError was not raised")
    except dataclasses.FrozenInstanceError:
        pass


def test_gameprofile_pack_reader_stored():
    """pack_reader is stored and accessible (loose Any type in 2.1)."""
    fake_reader = MagicMock()
    p = _make_profile(pack_reader=fake_reader)
    assert p.pack_reader is fake_reader
