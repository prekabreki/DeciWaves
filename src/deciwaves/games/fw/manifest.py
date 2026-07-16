"""FW labeled-manifest schema: the CSV column order every FW manifest writer shares.

Lives on its own (not in any one stage module) because it's consumed by several
independent stages (subtitle-bind, subtitle-match, story-full, weave, dlc, assemble)
that all read/write the same labeled-manifest shape.
"""

from __future__ import annotations

MANIFEST_COLS = ["line_id", "wav", "speaker", "subtitle", "gamescript_index",
                 "quest", "tier", "score", "transcript"]
