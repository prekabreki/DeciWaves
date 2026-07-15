"""GameProfile: per-game configuration seam for the Decima audio pipeline.

A frozen dataclass that carries the game-specific knobs the shared engine modules
actually read (the per-game ``catalog`` stage, ``engine.speakers``) so they can be
parameterised without hard-coding DS paths.  The PackReader Protocol is not yet
formalised; for now ``pack_reader`` is typed as ``Any``.

Usage::

    from deciwaves.engine.profile import GameProfile
    profile = GameProfile(
        pack_reader=pack_index,
        decima_version="DSPC",
        core_prefixes=CORE_PREFIXES,
        speaker_simpletext_filter=lambda p: "sentences/voices/" in p and p.endswith("/simpletext"),
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class GameProfile:
    """Immutable per-game configuration passed to engine modules.

    Only the fields that a game-agnostic module actually reads off a profile live
    here; DS-specific behaviour (episode ordering, cutscene resolution, transcript
    anchoring, output paths) is handled by the ``games.ds`` modules directly, not
    through this seam.

    Fields
    ------
    pack_reader
        Object that exposes ``read()``, ``read_core()``, ``has_core()`` on
        the game's archives.  Typed as ``Any`` until a ``PackReader`` Protocol
        is formalised.
    decima_version
        Decima engine version string passed to ``pydecima.reader.set_globals``
        (e.g. ``"DSPC"`` for Death Stranding PC Director's Cut).
    core_prefixes
        Mapping ``{virtual_path_prefix: category}`` used by the per-game
        ``catalog`` stage to select and classify ``.core`` sentence files.
    speaker_simpletext_filter
        Predicate applied to file-list lines to discover the per-voice
        simpletext cores used by ``engine.speakers.SpeakerMap``.  Mirrors the
        inline filter ``"sentences/voices/" in p and p.strip().endswith("/simpletext")``.
    """

    pack_reader: Any
    decima_version: str
    core_prefixes: dict  # dict[str, str] — path-prefix → category
    speaker_simpletext_filter: Callable  # Callable[[str], bool]
