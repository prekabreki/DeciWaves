"""PackReader over HZD Remastered's Forbidden-West package format.

Composes FwLocators (PackFileLocators.bin index) + DsarArchive (per-archive DSAR reader).
The virtual-path hash is identical to DS, so we reuse engine.pack.bin_archive.file_hash.
Satisfies engine.pack.base.PackReader structurally.
"""
from __future__ import annotations
import os

from deciwaves.engine.pack.bin_archive import file_hash
from deciwaves.engine.pack.fw_locators import FwLocators, Locator
from deciwaves.engine.pack.dsar_archive import DsarArchive


class FwPackage:
    def __init__(self, package_dir: str):
        self.package_dir = package_dir
        self._locators = FwLocators(os.path.join(package_dir, "PackFileLocators.bin"))
        self._archives: dict[str, DsarArchive] = {}  # lazily opened by name

    def _archive(self, name: str) -> DsarArchive:
        arc = self._archives.get(name)
        if arc is None:
            arc = DsarArchive(os.path.join(self.package_dir, name))
            self._archives[name] = arc
        return arc

    def _read_locator(self, loc: Locator) -> bytes:
        return self._archive(loc.archive).read(loc.offset, loc.length)

    def read(self, virtual_path_with_ext: str) -> bytes:
        loc = self._locators.lookup(file_hash(virtual_path_with_ext))
        if loc is None:
            raise KeyError(virtual_path_with_ext)
        return self._read_locator(loc)

    def read_core(self, virtual_path: str) -> bytes:
        return self.read(virtual_path + ".core")

    def has_core(self, virtual_path: str) -> bool:
        return self.has(virtual_path + ".core")

    def has(self, virtual_path_with_ext: str) -> bool:
        return file_hash(virtual_path_with_ext) in self._locators

    def read_by_hash(self, path_hash: int) -> bytes:
        """Read by a precomputed hash (also used by Phase-3 self-verify, which
        has no path string to hash — see :meth:`first_locator`)."""
        loc = self._locators.lookup(path_hash)
        if loc is None:
            raise KeyError(hex(path_hash))
        return self._read_locator(loc)

    @property
    def locators(self) -> FwLocators:
        """Public read-only view of the PackFileLocators index."""
        return self._locators

    def dsar_for(self, archive: str) -> DsarArchive:
        """Return the (lazily-opened, cached) DsarArchive for *archive*."""
        return self._archive(archive)

    def first_locator(self) -> Locator:
        # smallest non-empty .core resource (not .core.stream — those are raw payloads,
        # not RTTI streams, so we skip them for the self-verify gate)
        best = None
        for loc in self._locators._by_hash.values():
            if loc.length > 0 and not loc.archive.endswith(".stream"):
                if best is None or loc.length < best.length:
                    best = loc
        if best is None:
            raise RuntimeError("no non-empty .core resources in package")
        return best
