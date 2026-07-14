"""Assemble the continuous FW deliverable (#34): woven story + DLC epilogue.

Concatenates manifests in the given order into one stream, re-ranking
`gamescript_index` continuously so a single render produces "one long MP3" — the
woven main story first, then Burning Shores as the post-game epilogue (it unlocks
after the final main quest, so chronologically it belongs last).
"""

from __future__ import annotations

import argparse
import csv

from games.fw.bind import MANIFEST_COLS


def combine(manifests):
    """Concatenate manifest row-lists in order; re-rank gamescript_index 0..N."""
    rows = []
    for manifest in manifests:
        for r in manifest:
            row = dict(r)
            row["gamescript_index"] = len(rows)
            rows.append(row)
    return rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble continuous FW deliverable (story + DLC epilogue)")
    ap.add_argument("manifests", nargs="+", help="manifest CSVs, in play order (story first)")
    ap.add_argument("--out", default="out/fw/combined-manifest.csv")
    a = ap.parse_args(argv)

    rows = combine([_load_csv(m) for m in a.manifests])

    import os
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"combined {len(a.manifests)} manifests -> {len(rows)} rows -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
