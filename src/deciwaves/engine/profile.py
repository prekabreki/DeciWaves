"""GameProfile: per-game configuration seam for the Decima audio pipeline.

A frozen dataclass that carries all game-specific knobs so engine modules
(catalog, speakers, story_order) can be parameterised without hard-coding
DS paths.  The PackReader Protocol is defined later in Task 2.4; for now
pack_reader is typed as Any.

Usage::

    from deciwaves.engine.profile import GameProfile
    profile = GameProfile(
        name="ds",
        pack_reader=pack_index,
        decima_version="DSPC",
        core_prefixes=CORE_PREFIXES,
        speaker_simpletext_filter=lambda p: "sentences/voices/" in p and p.endswith("/simpletext"),
        transcript_path="",  # BYO narrative transcript path (see docs/BYO.md); "" disables anchoring
        out_dir="out/ds",
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class GameProfile:
    """Immutable per-game configuration passed to engine modules.

    Fields
    ------
    name
        Short game identifier (e.g. ``"ds"``).  Used for logging and directory
        naming.
    pack_reader
        Object that exposes ``read()``, ``read_core()``, ``has_core()`` on
        the game's archives.  Typed as ``Any`` until Task 2.4 defines the
        ``PackReader`` Protocol.
    decima_version
        Decima engine version string passed to ``pydecima.reader.set_globals``
        (e.g. ``"DSPC"`` for Death Stranding PC Director's Cut).
    core_prefixes
        Mapping ``{virtual_path_prefix: category}`` used by ``engine.catalog``
        to select and classify ``.core`` sentence files.  Mirrors
        ``engine.catalog.CORE_PREFIXES`` for DS.
    speaker_simpletext_filter
        Predicate applied to file-list lines to discover the per-voice
        simpletext cores used by ``engine.speakers.SpeakerMap``.  Mirrors the
        inline filter ``"sentences/voices/" in p and p.strip().endswith("/simpletext")``.
    transcript_path
        Absolute or repo-relative path to a narrative transcript used by
        ``engine.transcript_anchor.build_index`` to anchor scenes in story
        order.  Copyrighted game-script prose is BYO (see ``docs/BYO.md``) and
        not shipped in this repo; ``""`` (the DS default) disables anchoring
        and falls back to episode/scene order.
    out_dir
        Root output directory for derived files (catalog, playlist, speakers
        cache, etc.).  DS default: ``"out/ds"``.
    episode_map
        Optional module/object with DS-specific episode-ordering helpers
        (``cs_group``, ``fallback_group``, ``scene_number``, etc.) consumed
        by ``engine.story_order``.  ``None`` for games that don't yet need it.
    cutscene_resolver
        Optional callable or module used to resolve cutscene audio tracks
        (``games.ds.cutscene_audio``).  ``None`` when not applicable.
    """

    name: str
    pack_reader: Any
    decima_version: str
    core_prefixes: dict  # dict[str, str] — path-prefix → category
    speaker_simpletext_filter: Callable  # Callable[[str], bool]
    transcript_path: str
    out_dir: str
    episode_map: Optional[Any] = field(default=None)
    cutscene_resolver: Optional[Any] = field(default=None)
