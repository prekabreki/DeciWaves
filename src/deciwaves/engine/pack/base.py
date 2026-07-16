"""Abstract interface for pack readers.

Both the DS `PackIndex` (bin archives) and HZD's `hzd_package.HzdPackage` reader
satisfy this Protocol so `GameProfile.pack_reader` has a concrete type.

Using `typing.Protocol` (structural subtyping) so `PackIndex` and future
implementations need no inheritance change — they conform automatically if they
carry the three methods with matching signatures.

`@runtime_checkable` lets callers do ``isinstance(obj, PackReader)`` in tests
and guard code.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PackReader(Protocol):
    """Structural interface satisfied by any pack reader.

    Methods
    -------
    read(virtual_path_with_ext)
        Extract raw bytes for the exact virtual path (extension included,
        e.g. ``"localized/sentences/.../sentences.core"``).
    read_core(virtual_path)
        Convenience wrapper: appends ``.core`` and calls :meth:`read`.
    has_core(virtual_path)
        Return ``True`` if the pack contains a ``.core`` entry for *virtual_path*.
    has(virtual_path_with_ext)
        Return ``True`` if the pack contains an entry for the exact virtual path
        (extension included) — the generic existence check :meth:`read` mirrors,
        for arbitrary paths (not just the ``.core`` convention ``has_core`` tests).
        Lets callers test membership without reaching into a reader's internal
        hash table.
    read_by_hash(path_hash)
        Extract raw bytes directly by a precomputed path hash, skipping the
        string-hashing step in :meth:`read`. Useful for callers that already
        hold a hash (e.g. while iterating an index) and would otherwise need
        to reach into reader internals to resolve it.
    """

    def read(self, virtual_path_with_ext: str) -> bytes:
        ...

    def read_core(self, virtual_path: str) -> bytes:
        ...

    def has_core(self, virtual_path: str) -> bool:
        ...

    def has(self, virtual_path_with_ext: str) -> bool:
        ...

    def read_by_hash(self, path_hash: int) -> bytes:
        ...
