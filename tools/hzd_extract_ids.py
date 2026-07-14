"""Build out/hzd/line_ids.csv: line_id -> SoundResource GUID + SENTENCE uuid.

catalog.csv has the human columns (speaker, subtitle, ...) but NO GUID, because
HZD audio resolves separately. This walks the SAME sentence cores catalog.py walks
and emits, per line, the two 16-byte identities the runtime memory scanner hunts
for in a process dump:

    line_id, sound_resource_guid, sentence_uuid

GUIDs are 32-char lowercase hex in raw on-disk byte order -- the exact bytes
``pydecima`` reads via ``stream.read(16)`` and the exact bytes present in RAM.
``line_id`` matches catalog.csv so the two files join 1:1.

Invoke as a module (src/ must be on PYTHONPATH)::

    PYTHONPATH=src python -m tools.hzd_extract_ids --package <...\\LocalCacheDX12\\package>
    PYTHONPATH=src python tools/hzd_extract_ids.py --package <...>
"""
from __future__ import annotations
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from games.hzd.catalog import select_sentence_cores            # noqa: E402
from games.hzd.sentence_fw import parse_sentence_ids           # noqa: E402

DEFAULT_PACKAGE = (
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"
)
COLUMNS = ["line_id", "sound_resource_guid", "sentence_uuid"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", default=DEFAULT_PACKAGE,
                    help=r"HZDR LocalCacheDX12\package directory")
    ap.add_argument("--out", default="out/hzd/line_ids.csv")
    ap.add_argument("--errors", default="out/hzd/line_ids-errors.log")
    ap.add_argument("--sample-cap", type=int, default=0,
                    help="0 = whole pack; >0 caps records scanned during harvest")
    args = ap.parse_args(argv)

    from games.hzd.profile import build_profile
    from games.hzd.inventory import harvest_sentence_cores
    profile = build_profile(args.package)
    fw = profile.pack_reader

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    print("harvesting sentence-core paths (content scan)...", flush=True)
    harvested = harvest_sentence_cores(fw, sample_cap=args.sample_cap or None)
    paths = select_sentence_cores(harvested)
    print(f"{len(paths)} dialogue cores", flush=True)

    cores_ok = cores_failed = total_lines = line_errs = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fout, \
         open(args.errors, "w", encoding="utf-8") as ferr:
        writer = csv.DictWriter(fout, fieldnames=COLUMNS)
        writer.writeheader()
        for core_path in paths:
            errs: list[tuple[int, Exception]] = []
            try:
                core_bytes = fw.read_core(core_path)
                rows = parse_sentence_ids(
                    core_bytes, on_line_error=lambda i, e: errs.append((i, e)))
            except Exception as exc:  # fail-soft per core
                cores_failed += 1
                ferr.write(f"{core_path}\t{type(exc).__name__}: {exc}\n")
                continue
            for r in rows:
                writer.writerow({
                    "line_id": r.line_id,
                    "sound_resource_guid": r.sound_resource_guid.hex(),
                    "sentence_uuid": r.sentence_uuid.hex(),
                })
            for i, e in errs:
                ferr.write(f"{core_path}#{i}\t{type(e).__name__}: {e}\n")
                line_errs += 1
            cores_ok += 1
            total_lines += len(rows)
    print(f"done: {cores_ok} cores, {cores_failed} core-failures, "
          f"{total_lines} lines, {line_errs} line-failures -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
