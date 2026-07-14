"""Interpret a DirectStorage-captured PHYSICAL offset as locator stream key(s).

The Frida hook (tools/hzd_dstorage_hook.js) logs the physical (compressed-chunk)
offset DirectStorage reads from package.01.00.core.stream. This maps that back:
  physical offset -> DSAR chunk -> chunk's logical range -> locator entries (keys)
whose stream payload begins in that chunk. Combined with in-game timing of which
line played, that yields ground-truth line -> key pairs (Strategy C validation).

Usage:
    python tools/hzd_phys_to_key.py <physical_offset> [--package <dir>] [--archive name]
"""
from __future__ import annotations
import argparse
import os
import sys
from bisect import bisect_right

from deciwaves.engine.pack.fw_locators import FwLocators, Entry
from deciwaves.engine.pack.dsar_archive import DsarArchive

DEFAULT_PACKAGE = r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"
DEFAULT_ARCHIVE = "package.01.00.core.stream"


def load(package_dir: str, archive: str):
    loc = FwLocators(os.path.join(package_dir, "PackFileLocators.bin"))
    entries = loc.entries(archive)
    dsar = DsarArchive(os.path.join(package_dir, archive))
    return entries, dsar


def chunk_for_physical(dsar: DsarArchive, phys: int):
    """The chunk whose compressed (physical) range covers `phys` (floor match)."""
    coffs = [c.compressed_offset for c in dsar._chunks]
    i = bisect_right(coffs, phys) - 1
    if i < 0:
        return None
    return dsar._chunks[i]


def phys_to_keys(entries: list[Entry], dsar: DsarArchive, phys: int) -> list[int]:
    """Stream keys of locator entries whose payload begins inside `phys`'s chunk."""
    c = chunk_for_physical(dsar, phys)
    if c is None:
        return []
    lo, hi = c.offset, c.offset + c.size
    return [e.hash for e in entries if lo <= e.offset < hi]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("physical", type=lambda s: int(s, 0), help="physical offset from the Frida log")
    ap.add_argument("--package", default=DEFAULT_PACKAGE)
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    args = ap.parse_args()
    entries, dsar = load(args.package, args.archive)
    c = chunk_for_physical(dsar, args.physical)
    if c is None:
        print("no chunk covers that physical offset")
        return
    keys = phys_to_keys(entries, dsar, args.physical)
    print(f"chunk: physical 0x{c.compressed_offset:x}  logical 0x{c.offset:x}  size {c.size}")
    print(f"{len(keys)} candidate key(s) begin in this chunk:")
    for k in keys:
        print(f"  0x{k:016x}  (hi32=0x{k >> 32:08x})")


if __name__ == "__main__":
    main()
