"""Fast-path English-audio resolver for Forbidden West dialogue lines.

For *arithmetically clean* streaming groups -- those whose locator slice holds
exactly 12 locators per ``LocalizedSimpleSoundResource`` (one per dubbed-audio
language) -- the k-th LSSR's English clip is ``locators[locator_start + 12*k]``:
English sits at offset 0 of each 12-locator block. Validated byte-exact on the
retail install (54,435 lines; English is always block-offset 0 or absent --
never elsewhere). See ``.memories/fw-batch-extractor-status.md``.

This needs **no object walk** -- pure arithmetic over the streaming graph's type
table + locator table -- so it sidesteps both batch blockers (the slow pure-Python
walk; the ~8 unported ``MsgReadBinary`` layouts that desync it). It is fail-soft
by omission: it yields only lines it can prove. The remaining ~43% (non-clean
groups; arith-clean LSSRs whose 12-block has no English locator) need the full
:class:`~engine.pack.fw_object_reader.GroupReader` walk and are handled elsewhere.

The fast path gives audio + a stable id only. Speaker/subtitle come downstream
(ASR against ``docs/forbidden_west_gamescript.md``, the proven HZD path; or
link-table resolution of ``SentenceResource`` text refs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from engine.pack.fw_streaming_graph import Locator, StreamingGraph
from engine.pack.fw_rtti import type_hash

# Dubbed-audio languages per LSSR; English occupies block offset 0.
LANGS = 12

# An English voice stream: a path segment named ``en`` directly before the
# ``package.NN.MM.core.stream`` file. Matches the base game's two parts
# (``en/package.01.00`` + ``en/package.01.01``) AND the DLC
# (``dlc/en/package.01.00``) -- so Burning Shores + base overflow are included,
# while fr/es/de/... are excluded. The base graph indexes all of them in one
# Files table (verified: indices 15, 16, 101 on retail).
_EN_STREAM_RE = re.compile(r"(^|/)en/package\.\d+\.\d+\.core\.stream$")


@dataclass(frozen=True)
class FastLine:
    """One English dialogue line resolved by the fast path."""
    line_id: str        # stable: f"g{group_id}_{k:04d}" (k = LSSR ordinal in group)
    group_id: int
    lssr_index: int     # k: the LSSR's ordinal within the group (type-table order)
    locator: Locator    # the English StreamingDataSource locator (file_index == en)


def english_file_indices(graph: StreamingGraph) -> set[int]:
    """Indices in ``graph.files`` of every English voice stream (base parts +
    DLC). The device prefix ``cache:package/`` is stripped before matching."""
    return {
        i for i, f in enumerate(graph.files)
        if _EN_STREAM_RE.search(f.replace("cache:package/", ""))
    }


def iter_english_lines(graph: StreamingGraph,
                       en_indices: set[int] | None = None) -> Iterator[FastLine]:
    """Yield a :class:`FastLine` for every English clip the fast path can prove.

    *en_indices* overrides the set of accepted English stream file indices
    (defaults to :func:`english_file_indices` -- base parts **and** DLC). Each
    line's locator carries its own ``file_index``, so downstream reads from the
    right stream automatically.
    """
    en = english_file_indices(graph) if en_indices is None else en_indices
    if not en:
        raise KeyError("no English voice stream found in graph.files")
    lssr = type_hash("LocalizedSimpleSoundResource")
    file_index = graph.locators.file_index  # numpy view over all locators
    for grp in graph.groups:
        tt = graph.type_table[grp.type_start:grp.type_start + grp.type_count]
        n = int((tt == lssr).sum())
        if n == 0 or grp.locator_count != LANGS * n:
            continue  # not arith-clean -> needs the full walk
        base = grp.locator_start
        for k in range(n):
            idx = base + LANGS * k
            if int(file_index[idx]) in en:  # English present at block offset 0
                yield FastLine(f"g{grp.group_id}_{k:04d}", grp.group_id, k,
                               graph.locators[idx])
