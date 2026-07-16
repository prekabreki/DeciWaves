"""Schema-driven Decima (Forbidden West) RTTI type registry.

Loads odradek's generated ``types.json`` and reproduces its ordered-attribute
computation so a compound can be deserialised field-by-field exactly as the game
does. The two load-bearing details (ported from odradek):

* **Type id** = ``murmur3_x64_128(seed=42, "00000001_" + TypeName).low64`` — the
  ``"00000001_"`` is the type-database version stamp that prefixes every name.
* **Ordered attrs**: flatten base classes depth-first (skipping extension bases
  with negative offset), then own attrs, each tagged with its absolute C++
  offset; sort by offset with Decima's *deterministic randomised quicksort*
  (non-stable — ties resolve by a fixed LCG, so it must be replicated exactly);
  finally drop attrs whose ``flags & 2`` (``ATTR_DONT_SERIALIZE_BINARY``) is set.
  Property attrs are NOT dropped unless that flag is set.

Sources: ``HFWTypeFactory`` (hash + quicksort + filter),
``AbstractTypeFactory.collectOrderedAttrs``, ``ClassAttrInfo.isSerialized``.
"""
from __future__ import annotations

import json
import struct

from deciwaves.engine.pack.bin_archive import murmurhash3_x64_128

ATTR_DONT_SERIALIZE_BINARY = 2


def type_hash(name: str) -> int:
    """On-disk type id for *name* (prefixed murmur3 low64)."""
    return struct.unpack("<Q", murmurhash3_x64_128(("00000001_" + name).encode("utf-8"), 42)[:8])[0]


def _quicksort_by_offset(items: list) -> None:
    """Decima's deterministic randomised quicksort, in place. *items* are
    ``(name, type, offset)`` tuples; sort key is ``offset``. Replicates
    ``HFWTypeFactory.quicksort`` exactly (LCG state threaded through recursion,
    Hoare-style partition) so tied offsets land in the same order as the game."""
    def key(i):
        return items[i][2]

    def partition(left, right):
        start, end = left - 1, right
        while True:
            start += 1
            while start < end and key(start) < key(right):
                start += 1
            end -= 1
            while end > start and key(right) < key(end):
                end -= 1
            if start >= end:
                break
            items[start], items[end] = items[end], items[start]
        items[start], items[right] = items[right], items[start]
        return start

    def sort(left, right, state):
        if left < right:
            state = (0x19660D * state + 0x3C6EF35F) & 0xFFFFFFFF
            pivot = (state >> 8) % (right - left)
            items[left + pivot], items[right] = items[right], items[left + pivot]
            start = partition(left, right)
            state = sort(left, start - 1, state)
            state = sort(start + 1, right, state)
        return state

    sort(0, len(items) - 1, 0)


class TypeRegistry:
    def __init__(self, types_json_path: str):
        with open(types_json_path, "r", encoding="utf-8") as f:
            self.types: dict[str, dict] = json.load(f)
        # on-disk type id -> name (every type name hashed once)
        self._by_hash: dict[int, str] = {type_hash(n): n for n in self.types}
        self._ordered_attrs_cache: dict[str, tuple[tuple[str, str], ...]] = {}

    def name_for_hash(self, h: int) -> str:
        return self._by_hash[h]

    def kind(self, name: str) -> str:
        return self.types[name]["kind"]

    def define(self, name: str) -> dict:
        return self.types[name]

    def ordered_attrs(self, name: str) -> tuple[tuple[str, str], ...]:
        """Serialised ``(attr_name, attr_type)`` for compound *name*, in
        on-disk order. Collect (bases-first), sort by offset (with all attrs
        present, including non-serialised, so ties resolve as the game does),
        then drop ``flags & ATTR_DONT_SERIALIZE_BINARY``.

        Cached per-instance (not ``functools.lru_cache``, which keys on
        ``self`` and would pin every ``TypeRegistry`` -- and its loaded
        ``types.json`` -- alive for the process lifetime)."""
        if name in self._ordered_attrs_cache:
            return self._ordered_attrs_cache[name]
        collected: list[tuple[str, str, int, int]] = []
        self._collect(name, 0, collected)
        # sort by offset (index 2); _quicksort_by_offset reads item[2]
        _quicksort_by_offset(collected)
        result = tuple(
            (n, t) for (n, t, _off, flags) in collected
            if not (flags & ATTR_DONT_SERIALIZE_BINARY)
        )
        self._ordered_attrs_cache[name] = result
        return result

    def _collect(self, name: str, base_offset: int, out: list) -> None:
        d = self.types[name]
        for base in d.get("bases", []):
            if base["offset"] < 0:  # extension type
                continue
            self._collect(base["type"], base_offset + base["offset"], out)
        for attr in d.get("attrs", []):
            if "name" not in attr:  # category marker
                continue
            out.append((attr["name"], attr["type"], base_offset + attr["offset"], attr.get("flags", 0)))
