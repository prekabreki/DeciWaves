"""Cheap (A,B) per package.01 clip: A=locator length, B=ATRAC9 fact sample-count."""
from __future__ import annotations
import argparse
import csv
import os
from deciwaves.engine.parallel import default_jobs, ordered_parallel
from deciwaves.engine.pack.fw_package import FwPackage
from deciwaves.games.hzd.atrac9 import fact_sample_count

ARCHIVE = "package.01.00.core.stream"
COLUMNS = ["clip_row", "offset", "a_bytes", "b_samples"]


def clip_ab(dsar, entry, header_len=2048):
    a = entry.length
    head = dsar.read(entry.offset, min(header_len, a))
    b = fact_sample_count(head)
    return a, (b if b is not None else 0)


def build_clip_index(dsar, entries, out_path, errors_path, header_len=2048, jobs=1):
    """Write the (offset, a_bytes, b_samples) CSV for *entries*.

    Fail-soft per clip: a bad archive read (``ValueError`` from ``dsar.read`` --
    e.g. a truncated/out-of-range clip) is logged to *errors_path* with the
    clip's row index and skipped, never aborting the whole index. Returns the
    number of clips skipped.

    ``jobs`` reads/parses that many clip headers concurrently (``dsar.read``
    reopens the archive per call, so it is safe under the pool); ``jobs=1``
    (default) is the old serial pass. The header read+parse runs in workers, but
    every CSV row and error line is written on the calling thread in clip-row
    order, so the output file is byte-identical to the serial build.
    """
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    def _work(item):
        i, e = item
        try:
            a, b = clip_ab(dsar, e, header_len=header_len)
            return i, e.offset, a, b, None
        except ValueError as exc:  # fail-soft: reported by the main thread below
            return i, None, None, None, str(exc)

    skipped = 0
    with open(out_path, "w", newline="") as f, \
         open(errors_path, "w", encoding="utf-8") as ferr:
        w = csv.writer(f); w.writerow(COLUMNS)
        for i, offset, a, b, err in ordered_parallel(enumerate(entries), _work, jobs):
            if err is not None:
                ferr.write(f"{i}\t{err}\n"); ferr.flush()
                skipped += 1
                continue
            w.writerow([i, offset, a, b])
    return skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", default="out/hzd/clip-index.csv")
    ap.add_argument("--errors", default="out/hzd/clip-index-errors.log")
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="number of clip headers to read/parse concurrently. "
                         f"Default min(8, cpu_count)={default_jobs()}; --jobs 1 forces "
                         "the old serial pass")
    a = ap.parse_args(argv)
    pkg = FwPackage(a.package)                       # composes FwLocators + DsarArchive
    dsar = pkg.dsar_for(ARCHIVE)                     # lazy-cached DsarArchive
    entries = pkg.locators.entries(ARCHIVE)
    skipped = build_clip_index(dsar, entries, a.out, a.errors, jobs=a.jobs)
    msg = f"indexed {len(entries) - skipped} clips -> {a.out}"
    if skipped:
        msg += f" ({skipped} skipped, see {a.errors})"
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
