"""DS dump: decode selected line ids to WAV via clip_wav.

    deciwaves ds dump --ids <ids.txt> --out <dir> [--data-dir <DS:DC/data>] [--oodle <oo2core_7_win64.dll>]
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil

from deciwaves.cli import config
from deciwaves.engine.audio_clip import clip_wav
from deciwaves.engine.pack.bin_index import PackIndex


def _safe_name(line_id: str, used: set[str] | None = None) -> str:
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in line_id) or "clip"
    if used is not None:
        base = name
        i = 1
        while name in used:
            name = f"{base}_{i}"
            i += 1
    return name


def _load_catalog(csv_path: str) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    if not os.path.isfile(csv_path):
        return catalog
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lid = r.get("line_id", "")
            if lid:
                catalog[lid] = r
    return catalog


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DS: decode selected line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--data-dir", default=None,
                    help="DS:DC/data directory (default: ds_install/data from config)")
    ap.add_argument("--oodle", default=None,
                    help="path to oo2core_7_win64.dll (default: ds_install/oo2core_7_win64.dll from config)")
    ap.add_argument("--catalog", default="out/catalog.csv",
                    help="catalog CSV (default: out/catalog.csv)")
    a = ap.parse_args(argv)

    ids = [ln.strip() for ln in open(a.ids) if ln.strip()]
    if not ids:
        print("dump: ids file is empty -- nothing to do")
        return 0

    catalog = _load_catalog(a.catalog)

    data_dir = a.data_dir
    oodle = a.oodle
    if not data_dir or not oodle:
        cfg = config.load()
        ds_install = cfg.get("ds_install", "")
        if not data_dir:
            data_dir = os.path.join(ds_install, "data") if ds_install else None
        if not oodle:
            oodle = os.path.join(ds_install, "oo2core_7_win64.dll") if ds_install else None
    if not data_dir or not os.path.isdir(data_dir):
        print(f"dump: ERROR - DS data directory not found: {data_dir}. "
              "Provide --data-dir or run `deciwaves setup`.")
        return 1
    if not oodle or not os.path.isfile(oodle):
        print(f"dump: ERROR - Oodle DLL not found: {oodle}. "
              "Provide --oodle or run `deciwaves setup`.")
        return 1

    idx = PackIndex(data_dir, oodle)
    cache_dir = os.path.join(a.out, ".wav-cache")
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    unknown = 0
    failed = 0
    ok = 0
    used_names: set[str] = set()

    for line_id in ids:
        row = catalog.get(line_id)
        if row is None:
            print(f"dump: WARNING - unknown line_id: {line_id}")
            unknown += 1
            continue
        wem_path = row.get("wem_path_en", "")
        if not wem_path:
            print(f"dump: WARNING - {line_id}: no wem_path_en in catalog")
            failed += 1
            continue
        try:
            wav_path, _dur = clip_wav(idx, wem_path, cache_dir)
            safe = _safe_name(line_id, used_names)
            used_names.add(safe)
            dst = os.path.join(a.out, f"{safe}.wav")
            if os.path.abspath(wav_path) != os.path.abspath(dst):
                shutil.copyfile(wav_path, dst)
            ok += 1
        except Exception as exc:
            print(f"dump: WARNING - {line_id}: decode failed: {exc}")
            failed += 1

    print(f"dump: {ok} ok, {failed} failed, {unknown} unknown")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
