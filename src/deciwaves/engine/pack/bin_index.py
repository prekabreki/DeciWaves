"""Index over all DS:DC .bin archives: resolve a virtual path to extracted bytes."""
from __future__ import annotations
import glob
import os

from deciwaves.engine.pack.bin_archive import BinArchive, file_hash


class PackIndex:
    def __init__(self, data_dir: str, oodle_dll: str):
        self.oodle_dll = oodle_dll
        self._by_hash: dict[int, tuple[BinArchive, object]] = {}
        for path in sorted(glob.glob(os.path.join(data_dir, "*.bin"))):
            arc = BinArchive(path)
            arc.open_index()
            for entry in arc.file_table:
                # first archive wins on duplicate hashes
                self._by_hash.setdefault(entry.hash, (arc, entry))

    def read(self, virtual_path_with_ext: str) -> bytes:
        h = file_hash(virtual_path_with_ext)
        hit = self._by_hash.get(h)
        if hit is None:
            raise KeyError(virtual_path_with_ext)
        arc, entry = hit
        return arc.extract(entry, self.oodle_dll)

    def read_core(self, virtual_path: str) -> bytes:
        return self.read(virtual_path + ".core")

    def has_core(self, virtual_path: str) -> bool:
        return self.has(virtual_path + ".core")

    def has(self, virtual_path_with_ext: str) -> bool:
        return file_hash(virtual_path_with_ext) in self._by_hash

    def read_by_hash(self, path_hash: int) -> bytes:
        hit = self._by_hash.get(path_hash)
        if hit is None:
            raise KeyError(hex(path_hash))
        arc, entry = hit
        return arc.extract(entry, self.oodle_dll)
