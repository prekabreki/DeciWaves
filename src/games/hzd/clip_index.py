"""Cheap (A,B) per package.01 clip: A=locator length, B=ATRAC9 fact sample-count."""
from __future__ import annotations
import argparse, csv, os
from engine.pack.fw_package import FwPackage
from games.hzd.atrac9 import fact_sample_count

ARCHIVE = "package.01.00.core.stream"
COLUMNS = ["clip_row", "offset", "a_bytes", "b_samples"]


def clip_ab(dsar, entry, header_len=2048):
    a = entry.length
    head = dsar.read(entry.offset, min(header_len, a))
    b = fact_sample_count(head)
    return a, (b if b is not None else 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", default="out/hzd/clip-index.csv")
    a = ap.parse_args(argv)
    pkg = FwPackage(a.package)                       # composes FwLocators + DsarArchive
    dsar = pkg.dsar_for(ARCHIVE)                     # lazy-cached DsarArchive
    entries = pkg.locators.entries(ARCHIVE)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(COLUMNS)
        for i, e in enumerate(entries):
            ab = clip_ab(dsar, e)
            w.writerow([i, e.offset, ab[0], ab[1]])
    print(f"indexed {len(entries)} clips -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
