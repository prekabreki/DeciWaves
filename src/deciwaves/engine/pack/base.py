"""Abstract interface for pack readers.

Both the DS `PackIndex` (bin archives) and the future HZD `fw_package` reader
must satisfy this Protocol so `GameProfile.pack_reader` has a concrete type.

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
    """

    def read(self, virtual_path_with_ext: str) -> bytes:
        ...

    def read_core(self, virtual_path: str) -> bytes:
        ...

    def has_core(self, virtual_path: str) -> bool:
        ...
