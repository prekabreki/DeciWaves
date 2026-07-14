"""Phase-3 Task-5: HZD Remastered .core type-hash census probe.

Walk a bounded sample of .core resources (non-.stream archives) from the HZDR
package, parse each as a Decima RTTI stream, tally the leading type-hash of each
top-level object. Feeds Phase-4 resource-type mapping work.

Run:
    ./.venv/Scripts/python.exe tools/probe_hzd_census.py
"""
from __future__ import annotations
import struct
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PACKAGE_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"
SAMPLE_CAP = 5000          # max qualifying records to sample
MAX_BYTES   = 2_000_000    # skip records larger than this (textures/audio)


# ---------------------------------------------------------------------------
# RTTI walk — adapted from tests/test_fw_package.py::_rtti_walk_len
# Returns (leading_type_hash: int | None, consumed: int)
# leading_type_hash is None if buf is empty.
# consumed == -1 means the buffer is NOT a clean RTTI stream.
# ---------------------------------------------------------------------------
def _rtti_walk(buf: bytes) -> tuple[int | None, int]:
    pos = 0
    n = len(buf)
    leading: int | None = None
    while pos < n:
        if pos + 12 > n:
            return leading, -1
        type_hash, size = struct.unpack_from("<QI", buf, pos)
        if leading is None:
            leading = type_hash
        pos += 12 + size
        if pos > n:
            return leading, -1
    return leading, pos


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Late import so the script fails fast with a clear message if the package
    # dir is missing rather than after the potentially slow import.
    import os
    if not os.path.isdir(PACKAGE_DIR):
        sys.exit(f"ERROR: HZDR package dir not found: {PACKAGE_DIR}")

    from deciwaves.engine.pack.fw_package import FwPackage

    print(f"Opening FwPackage at: {PACKAGE_DIR}", flush=True)
    fw = FwPackage(PACKAGE_DIR)

    total_qualifying = 0
    total_too_large   = 0
    total_sampled     = 0
    total_read_ok     = 0
    total_clean       = 0
    total_failed      = 0

    leading_hashes: Counter[int] = Counter()

    for path_hash, loc in fw._locators._by_hash.items():
        # Only .core archives — skip .core.stream (raw audio/texture payloads)
        if loc.archive.endswith(".stream"):
            continue

        total_qualifying += 1

        if total_sampled >= SAMPLE_CAP:
            # Count remaining qualifying records for reporting but don't sample
            continue

        if loc.length > MAX_BYTES:
            total_too_large += 1
            continue

        total_sampled += 1

        try:
            raw = fw.read_by_hash(path_hash)
        except Exception:
            total_failed += 1
            continue

        total_read_ok += 1

        try:
            leading, consumed = _rtti_walk(raw)
        except Exception:
            total_failed += 1
            continue

        if consumed != len(raw):
            # Not a clean RTTI stream — don't count its leading hash
            continue

        total_clean += 1
        if leading is not None:
            leading_hashes[leading] += 1

        if total_sampled % 500 == 0:
            print(f"  ... sampled {total_sampled}/{SAMPLE_CAP}, clean so far: {total_clean}", flush=True)

    # --- Summary ---
    print()
    print("=" * 60)
    print("HZD Remastered .core type-hash census")
    print("=" * 60)
    print(f"  Total qualifying records (non-.stream):  {total_qualifying}")
    print(f"  Sampled (cap={SAMPLE_CAP}, max_size={MAX_BYTES:,}):      {total_sampled}")
    print(f"  Skipped (too large):                     {total_too_large}")
    print(f"  Read-OK:                                 {total_read_ok}")
    print(f"  Clean RTTI (consumed == len):            {total_clean}")
    print(f"  Failed (read or walk error):             {total_failed}")
    print(f"  Not-clean-RTTI (walk mismatch):          {total_read_ok - total_clean}")
    print()
    print(f"Top {min(30, len(leading_hashes))} leading type-hashes by frequency:")
    print(f"  {'Hash':>18}  {'Count':>7}")
    print(f"  {'-'*18}  {'-'*7}")
    for h, count in leading_hashes.most_common(30):
        print(f"  0x{h:016X}  {count:>7}")
    print("=" * 60)


if __name__ == "__main__":
    main()
