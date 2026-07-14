"""Speaker display-name resolution for DS:DC voice codes.

Reads ``localized/sentences/voices/<stem>/simpletext`` cores (each contains a
``LocalizedTextResource`` whose first language string is the English display
name) and builds a ``{vr_stem: name}`` map cached to ``out/speakers.json``.

Usage::

    smap = SpeakerMap(pack_index, file_list_lines, cache_path="out/speakers.json")
    name = smap.name_for("localized/voices/vr0010_sam")  # -> "Sam"
"""
from __future__ import annotations

import io
import json
import os
from typing import Callable, Sequence

import pydecima.reader as reader
from pydecima.resources.LocalizedTextResource import LocalizedTextResource

#: Default predicate that matches DS:DC simpletext cores in the file list.
_DS_SIMPLETEXT_FILTER: Callable[[str], bool] = (
    lambda p: "sentences/voices/" in p and p.strip().endswith("/simpletext")
)


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
        if cache_path and os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                self._map: dict[str, str] = json.load(f)
        else:
            simpletext_paths = [
                p.strip()
                for p in file_list_lines
                if simpletext_filter(p)
            ]
            self._map = self._build_map(index, simpletext_paths)
            if cache_path:
                os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(self._map, f, ensure_ascii=False, indent=2)

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
                        if name:
                            result[stem] = name
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
