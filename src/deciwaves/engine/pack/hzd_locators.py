"""Parse HZD Remastered's PackFileLocators.bin: path-hash -> (archive, offset, length).

Layout (little-endian), confirmed against the retail install; see .memories/hzd-pack-format.md:
    u32 NumPackfiles
    per packfile: u32 NameLength; char Name[NameLength]; u32 NumFiles;
                  NumFiles x { u64 path_hash; u32 offset; u32 length }
The archive index is implicit (the enclosing packfile group).

Retail files carry a short trailing section after the last packfile record (observed:
39 bytes naming ShaderBinaries.bin -- see the memory above). The parse warns loudly
about unconsumed bytes rather than raising: a genuinely truncated file still fails
hard inside the record loop (struct.error), so only the benign over-run is tolerated.
"""
from __future__ import annotations
import struct
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Locator:
    """One ``PackFileLocators.bin`` index entry: an (archive, offset, length)
    triple locating a resource inside a DSAR archive.

    Not the same concept as :class:`engine.pack.fw_streaming_graph.Locator`,
    which addresses a streamed audio payload by ``(file_index, offset)`` into
    Forbidden West's ``streaming_graph.core`` positional index -- different
    on-disk index format, different fields, different game path (HZD
    Remastered here vs. real FW there).
    """
    archive: str
    offset: int
    length: int


@dataclass(frozen=True)
class Entry:
    """One raw PackFileLocators record, in file order (duplicates kept)."""
    archive: str
    hash: int
    offset: int
    length: int


class HzdLocators:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            self._init_from(f.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> "HzdLocators":
        self = cls.__new__(cls)
        self._init_from(data)
        return self

    def _init_from(self, data: bytes) -> None:
        self._by_hash: dict[int, Locator] = {}
        self._ordered: list[Entry] = []
        self._archives: list[str] = []
        pos = 0
        (num_packfiles,) = struct.unpack_from("<I", data, pos); pos += 4
        for _ in range(num_packfiles):
            (name_len,) = struct.unpack_from("<I", data, pos); pos += 4
            name = data[pos:pos + name_len].decode("utf-8"); pos += name_len
            self._archives.append(name)
            (num_files,) = struct.unpack_from("<I", data, pos); pos += 4
            for _ in range(num_files):
                h, off, length = struct.unpack_from("<QII", data, pos); pos += 16
                self._ordered.append(Entry(name, h, off, length))
                # first packfile wins on duplicate hash (mirror DS PackIndex.setdefault)
                self._by_hash.setdefault(h, Locator(name, off, length))
        self.trailing_bytes = len(data) - pos
        if self.trailing_bytes:
            print(
                f"WARNING: PackFileLocators parse left {self.trailing_bytes} "
                f"unconsumed trailing bytes ({len(self._archives)} archives / "
                f"{len(self._ordered)} records parsed OK; retail files ship a "
                f"trailing loose-file section, so this is expected on a real install)",
                file=sys.stderr,
            )

    def lookup(self, path_hash: int) -> Locator | None:
        return self._by_hash.get(path_hash)

    def entries(self, archive: str | None = None) -> list[Entry]:
        """Raw records in file order (duplicates preserved), optionally one archive."""
        if archive is None:
            return list(self._ordered)
        return [e for e in self._ordered if e.archive == archive]

    def items(self) -> list[tuple[int, Locator]]:
        """Deduped ``(path_hash, Locator)`` pairs (first-packfile-wins), mirroring
        :meth:`lookup`/:meth:`__contains__` — the public counterpart to iterating
        the internal hash table directly."""
        return list(self._by_hash.items())

    def __contains__(self, path_hash: int) -> bool:
        return path_hash in self._by_hash

    @property
    def archives(self) -> list[str]:
        return list(self._archives)

    def __len__(self) -> int:
        return len(self._by_hash)

    @property
    def duplicate_count(self) -> int:
        """How many raw records were collapsed by first-packfile-wins
        deduping (``len(entries()) - len(self)``)."""
        return len(self._ordered) - len(self._by_hash)
