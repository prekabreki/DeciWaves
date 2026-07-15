"""Cheap (A,B) per package.01 clip: A=locator length, B=ATRAC9 fact sample-count."""
from __future__ import annotations
import argparse
import csv
import os
from deciwaves.engine.pack.fw_package import FwPackage
from deciwaves.games.hzd.atrac9 import fact_sample_count

ARCHIVE = "package.01.00.core.stream"
COLUMNS = ["clip_row", "offset", "a_bytes", "b_samples"]


def clip_ab(dsar, entry, header_len=2048):
    a = entry.length
    head = dsar.read(entry.offset, min(header_len, a))
    b = fact_sample_count(head)
    return a, (b if b is not None else 0)


def build_clip_index(dsar, entries, out_path, errors_path, header_len=2048):
    """Write the (offset, a_bytes, b_samples) CSV for *entries*.

    Fail-soft per clip: a bad archive read (``ValueError`` from ``dsar.read`` --
    e.g. a truncated/out-of-range clip) is logged to *errors_path* with the
    clip's row index and skipped, never aborting the whole index. Returns the
    number of clips skipped.
    """
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    skipped = 0
    with open(out_path, "w", newline="") as f, \
         open(errors_path, "w", encoding="utf-8") as ferr:
        w = csv.writer(f); w.writerow(COLUMNS)
        for i, e in enumerate(entries):
            try:
                ab = clip_ab(dsar, e, header_len=header_len)
            except ValueError as exc:  # fail-soft: log clip + reason, keep going
                ferr.write(f"{i}\t{exc}\n"); ferr.flush()
                skipped += 1
                continue
            w.writerow([i, e.offset, ab[0], ab[1]])
    return skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", default="out/hzd/clip-index.csv")
    ap.add_argument("--errors", default="out/hzd/clip-index-errors.log")
    a = ap.parse_args(argv)
    pkg = FwPackage(a.package)                       # composes FwLocators + DsarArchive
    dsar = pkg.dsar_for(ARCHIVE)                     # lazy-cached DsarArchive
    entries = pkg.locators.entries(ARCHIVE)
    skipped = build_clip_index(dsar, entries, a.out, a.errors)
    msg = f"indexed {len(entries) - skipped} clips -> {a.out}"
    if skipped:
        msg += f" ({skipped} skipped, see {a.errors})"
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
