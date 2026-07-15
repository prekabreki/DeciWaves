"""Speaker display-name resolution for DS:DC voice codes.

Reads ``localized/sentences/voices/<stem>/simpletext`` cores (each contains a
``LocalizedTextResource``) and builds a ``{vr_stem: name}`` map cached to
``out/speakers.json``. Index 0 is usually the English display name, but the
vendored scanner skips empty language slots, so an empty English slot silently
shifts index 0 onto the first non-empty language instead (issue #3). A guard
rejects non-Latin text at index 0; when that happens, the remaining language
slots are scanned in order for the first non-empty, plausibly-English sibling
(character names are frequently identical Latin text across locales) before
falling back to a stem-derived name.

Usage::

    smap = SpeakerMap(pack_index, file_list_lines, cache_path="out/speakers.json")
    name = smap.name_for("localized/voices/vr0010_sam")  # -> "Sam"
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Callable, Sequence

import deciwaves._vendor.pydecima.reader as reader
from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
from deciwaves.engine.text_lang import is_plausibly_english

#: Default predicate that matches DS:DC simpletext cores in the file list.
_DS_SIMPLETEXT_FILTER: Callable[[str], bool] = (
    lambda p: "sentences/voices/" in p and p.strip().endswith("/simpletext")
)

#: speakers.json cache schema version. Bump whenever a change to
#: _build_map's selection logic would make previously-cached names wrong
#: (issue #3: caches from before this fix could hold Japanese names spilled
#: from the language[0] shift bug; T6b: caches from before sibling-slot
#: recovery could hold a stem-derived guess where a sibling language slot
#: now yields the real Latin display name instead) -- a mismatched/absent
#: marker forces a full rebuild instead of silently trusting stale disk
#: content.
_SCHEMA_VERSION = 3

#: Strips a leading "<letters><digits>_" voice-code prefix (e.g. "vr0010_")
#: off a stem, leaving the human-readable slug behind.
_STEM_PREFIX_RE = re.compile(r"^[A-Za-z]+\d+_")


def _name_from_stem(stem: str) -> str:
    """Best-effort display name derived from a voice stem (e.g. ``vr0010_sam``).

    Used only as a last-resort fallback when a simpletext core's index-0
    text exists but is not plausibly English (the empty-English-slot shift
    case, issue #3) -- never as a substitute for a real accepted name.
    Never returns an empty string for a non-empty *stem*.
    """
    slug = _STEM_PREFIX_RE.sub("", stem, count=1) or stem
    words = [w for w in re.split(r"[_\-]+", slug) if w]
    return " ".join(w.capitalize() for w in words) if words else stem


class SpeakerMap:
    """Map voice codes (e.g. ``vr0010_sam``) to human display names."""

    def __init__(
        self,
        index,
        file_list_lines: Sequence[str],
        cache_path: str = "out/speakers.json",
        simpletext_filter: Callable[[str], bool] | None = None,
    ) -> None:
        if simpletext_filter is None:
            simpletext_filter = _DS_SIMPLETEXT_FILTER
        cached_map = self._load_cache(cache_path) if cache_path else None
        if cached_map is not None:
            self._map: dict[str, str] = cached_map
        else:
            simpletext_paths = [
                p.strip()
                for p in file_list_lines
                if simpletext_filter(p)
            ]
            self._map = self._build_map(index, simpletext_paths)
            if cache_path:
                self._write_cache(cache_path, self._map)

    @staticmethod
    def _load_cache(cache_path: str) -> dict[str, str] | None:
        """Load the speakers.json cache if present AND at the current
        schema version; otherwise return None so the caller rebuilds.

        A missing/mismatched ``schema_version`` marker (absent -- the
        pre-fix unversioned format -- or older than ``_SCHEMA_VERSION``)
        means the cache predates this fix and may hold names computed by
        the old, buggy selection logic; it is never trusted.
        """
        if not os.path.isfile(cache_path):
            return None
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(cached, dict) or cached.get("schema_version") != _SCHEMA_VERSION:
            return None
        speakers = cached.get("speakers")
        return speakers if isinstance(speakers, dict) else None

    @staticmethod
    def _write_cache(cache_path: str, speaker_map: dict[str, str]) -> None:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {"schema_version": _SCHEMA_VERSION, "speakers": speaker_map},
                f, ensure_ascii=False, indent=2,
            )

    @staticmethod
    def _build_map(index, simpletext_paths: Sequence[str]) -> dict[str, str]:
        """Read each simpletext core and extract the display name."""
        result: dict[str, str] = {}
        for vp in simpletext_paths:
            # Extract stem from the simpletext core path tree
            # (localized/sentences/voices/vrXXXX_*/simpletext): use parts[-2],
            # the vrXXXX_* folder that contains "/simpletext".  name_for() uses
            # parts[-1] of the voice path tree (localized/voices/vrXXXX_*) —
            # both sides are joined on the shared vrXXXX_* stem.
            parts = vp.rstrip("/").split("/")
            if len(parts) < 2:
                continue
            stem = parts[-2]

            try:
                core_bytes = index.read_core(vp)
            except KeyError:
                continue  # path absent in archives

            objs: dict = {}
            try:
                reader.read_objects_from_stream(io.BytesIO(core_bytes), objs)
            except Exception:
                continue  # parse failure — skip

            for obj in objs.values():
                if isinstance(obj, LocalizedTextResource):
                    if obj.language:
                        name = obj.language[0]
                        if name and is_plausibly_english(name):
                            result[stem] = name
                        elif name:
                            # Non-empty but not plausibly English: the
                            # vendored scanner skips empty language slots,
                            # so an empty English slot shifts index 0 onto
                            # the first non-empty language (issue #3) --
                            # never surface that wrong-language text.
                            # Character display names are frequently
                            # identical Latin text across locales, so
                            # scan the remaining slots in order for the
                            # first non-empty, plausibly-English sibling
                            # (T6b) before giving up on a stem guess.
                            sibling = next(
                                (lang for lang in obj.language[1:]
                                 if lang and is_plausibly_english(lang)),
                                None,
                            )
                            result[stem] = (
                                sibling if sibling is not None
                                else _name_from_stem(stem)
                            )
                        # else: no text at all -- leave unmapped, exactly
                        # as before (name_for() falls back to "").
                    # Assumption: each simpletext core holds exactly one
                    # LocalizedTextResource; take the first match and stop
                    # (dict/file ordering is deterministic).
                    break

        return result

    def __len__(self) -> int:
        return len(self._map)

    def name_for(self, speaker_code: str) -> str:
        """Return the display name for *speaker_code*, or ``""`` if unknown.

        *speaker_code* may be a full virtual path (``localized/voices/vr0010_sam``)
        or just the stem (``vr0010_sam``).
        """
        if not speaker_code:
            return ""
        # Extract the last path segment as the stem
        stem = speaker_code.rstrip("/").split("/")[-1]
        return self._map.get(stem, "")
