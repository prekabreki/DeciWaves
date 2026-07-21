"""DS dump: decode selected line ids to WAV via clip_wav."""
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


def _load_ids(path: str) -> list[str]:
    lines = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                lines.append(ln)
    return lines


def _load_catalog(csv_path: str) -> dict[str, str]:
    """line_id -> stream path (stream_path or wem_path_en) from catalog or playlist CSV."""
    if not os.path.isfile(csv_path):
        return {}
    mapping: dict[str, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lid = row.get("line_id", "")
            if not lid:
                continue
            stream = row.get("stream_path") or row.get("wem_path_en") or ""
            if stream:
                mapping[lid] = stream
    return mapping


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Decode DS line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with line_ids (one per line)")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--catalog", default="out/ds/playlist.csv",
                    help="catalog or playlist CSV with line_id -> stream path mapping "
                         "(default out/ds/playlist.csv; falls back to catalog.csv)")
    ap.add_argument("--cache", default="out/wav-cache",
                    help="wav decode cache dir (default out/wav-cache)")
    a = ap.parse_args(argv)

    cfg = config.load()
    data_dir, oodle = config.resolve_ds_install(cfg)
    if not data_dir or not oodle:
        print("DS install is not configured. Run `deciwaves setup` first.")
        return 1

    catalog = _load_catalog(a.catalog)
    if not catalog:
        fallback = os.path.join(os.path.dirname(a.catalog), "catalog.csv")
        if os.path.isfile(fallback):
            catalog = _load_catalog(fallback)
    if not catalog:
        print(f"No catalog data found at {a.catalog} or catalog.csv -- "
              f"run `deciwaves ds catalog` first.")
        return 1

    ids = _load_ids(a.ids)
    if not ids:
        print("No line ids to process.")
        return 0

    idx = PackIndex(data_dir, oodle)
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)

    used: set[str] = set()
    ok = skipped = 0
    for lid in ids:
        stream = catalog.get(lid)
        if not stream:
            print(f"WARNING: line_id {lid!r} not found in catalog -- skipping")
            skipped += 1
            continue
        try:
            wav_path, _dur = clip_wav(idx, stream, a.cache)
            safe = _safe_name(lid, used)
            used.add(safe)
            dst = os.path.join(a.out, f"{safe}.wav")
            if os.path.abspath(wav_path) != os.path.abspath(dst):
                shutil.copy2(wav_path, dst)
            ok += 1
        except Exception as exc:
            print(f"WARNING: could not decode line_id {lid!r}: {exc} -- skipping")
            skipped += 1

    print(f"dump: {ok} ok, {skipped} skipped -> {a.out}")
    return 1 if skipped and not ok else 0
