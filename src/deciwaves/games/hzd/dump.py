"""HZD dump: decode selected line ids to WAV via clip-index coords + decode_wem_to_wav.

Requires a prior ``bind`` stage (asr-manifest.csv + clip-index.csv).

    deciwaves hzd dump --ids <ids.txt> --out <dir> [--package <...LocalCacheDX12/package>]
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil

from deciwaves.cli import config
from deciwaves.games.hzd.atrac9 import decode_wem_to_wav
from deciwaves.engine.pack.hzd_package import HzdPackage
from deciwaves.games.hzd.profile import VOICE_ARCHIVE


def _safe_name(line_id: str, used: set[str] | None = None) -> str:
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in line_id) or "clip"
    if used is not None:
        base = name
        i = 1
        while name in used:
            name = f"{base}_{i}"
            i += 1
    return name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HZD: decode selected line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--package", default=None,
                    help="HZDR package directory (default: hzd_package from config)")
    ap.add_argument("--manifest", default="out/hzd/asr-manifest.csv",
                    help="asr-manifest CSV from bind stage (default: out/hzd/asr-manifest.csv)")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv",
                    help="clip-index CSV from clip-index stage (default: out/hzd/clip-index.csv)")
    ap.add_argument("--catalog", default="out/hzd/catalog.csv",
                    help="catalog CSV (default: out/hzd/catalog.csv)")
    ap.add_argument("--cache", default="out/hzd/wav-cache",
                    help="decode cache directory (default: out/hzd/wav-cache)")
    a = ap.parse_args(argv)

    ids = [ln.strip() for ln in open(a.ids) if ln.strip()]
    if not ids:
        print("dump: ids file is empty -- nothing to do")
        return 0

    # Pre-bind guard: the manifest must exist and have bound clips.
    if not os.path.isfile(a.manifest):
        print("dump: ERROR - bind artifacts not found: asr-manifest.csv is missing. "
              "Run `deciwaves hzd bind` first.")
        return 1

    line_to_clip: dict[str, str] = {}
    with open(a.manifest, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lid = r.get("line_id", "")
            cr = r.get("clip_row", "")
            if lid and cr:
                line_to_clip[lid] = cr

    if not line_to_clip:
        print("dump: ERROR - asr-manifest.csv has no bound clips. "
              "Run `deciwaves hzd bind` first.")
        return 1

    clip_to_coords: dict[int, tuple[int, int]] = {}
    with open(a.clip_index, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                cr = int(r["clip_row"])
                clip_to_coords[cr] = (int(r["offset"]), int(r["a_bytes"]))
            except (KeyError, TypeError, ValueError):
                continue

    catalog: dict[str, dict] = {}
    if os.path.isfile(a.catalog):
        with open(a.catalog, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                catalog[r["line_id"]] = r

    # Resolve package from config if not given on CLI.
    pkg_dir = a.package
    if not pkg_dir:
        pkg_dir = config.load().get("hzd_package", "")
    if not pkg_dir or not os.path.isdir(pkg_dir):
        print("dump: ERROR - HZD package directory not found. "
              "Provide --package or run `deciwaves setup --hzd-package`.")
        return 1

    pkg = HzdPackage(pkg_dir)
    dsar = pkg.dsar_for(VOICE_ARCHIVE)
    os.makedirs(a.cache, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    unknown = 0
    failed = 0
    ok = 0
    used_names: set[str] = set()

    for line_id in ids:
        clip_row_str = line_to_clip.get(line_id)
        if clip_row_str is None:
            if line_id in catalog:
                print(f"dump: WARNING - {line_id}: catalog entry exists but no audio clip "
                      f"is bound. Run `deciwaves hzd bind` first.")
            else:
                print(f"dump: WARNING - unknown line_id: {line_id}")
            unknown += 1
            continue

        try:
            cr = int(clip_row_str)
        except (TypeError, ValueError):
            print(f"dump: WARNING - {line_id}: invalid clip_row {clip_row_str!r}")
            failed += 1
            continue

        coords = clip_to_coords.get(cr)
        if coords is None:
            print(f"dump: WARNING - {line_id}: no clip coordinates for clip_row {cr}")
            failed += 1
            continue

        wav_path = os.path.join(a.cache, f"{cr}.wav")
        try:
            if not (os.path.isfile(wav_path) and os.path.getsize(wav_path) > 44):
                wem = dsar.read(*coords)
                decode_wem_to_wav(wem, wav_path)
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
