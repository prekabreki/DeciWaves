"""DS dump stage: decode selected line IDs to WAV files.

Reads a file with one line_id per line, looks up the stream path in a
catalog CSV (playlist.csv by default, falling back to catalog.csv), and
decodes each to a WAV via clip_wav.
"""
from __future__ import annotations

import csv
import os
import shutil
import sys

from deciwaves.cli import config
from deciwaves.engine.audio_clip import clip_wav, ClipError
from deciwaves.engine.pack.bin_index import PackIndex


def _load_catalog(csv_path: str) -> dict[str, str]:
    if not os.path.isfile(csv_path):
        return {}
    mapping: dict[str, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lid = row.get("line_id", "")
            if not lid:
                continue
            stream = row.get("stream_path")
            if not stream:
                wem = row.get("wem_path_en") or ""
                stream = wem + ".core.stream" if wem else ""
            if stream:
                mapping[lid] = stream
    return mapping


def _read_ids(path: str) -> list[str]:
    ids: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(line)
    return ids


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="DS: decode selected lines to WAV files")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--catalog", default="out/playlist.csv",
                    help="catalog CSV (default: out/playlist.csv; falls back to out/catalog.csv)")
    ap.add_argument("--out", default="out/dump", help="output directory for WAVs")
    a = ap.parse_args(argv)

    cfg = config.load()
    data_dir, oodle = config.resolve_ds_install(cfg)
    if not data_dir or not oodle:
        print("deciwaves ds dump: DS install is not configured. Run `deciwaves setup` first.",
              file=sys.stderr)
        return 1

    ids = _read_ids(a.ids)
    if not ids:
        print("deciwaves ds dump: no line IDs in --ids file", file=sys.stderr)
        return 1

    catalog = _load_catalog(a.catalog)
    if not catalog:
        fallback = a.catalog.replace("playlist.csv", "catalog.csv")
        if fallback != a.catalog:
            catalog = _load_catalog(fallback)
        if not catalog:
            print(f"deciwaves ds dump: no catalog found at {a.catalog}", file=sys.stderr)
            return 1

    os.makedirs(a.out, exist_ok=True)
    idx = PackIndex(data_dir, oodle)
    cache_dir = os.path.join(a.out, ".cache")
    ok = 0
    missing = 0
    errors = 0
    for lid in ids:
        stream = catalog.get(lid)
        if not stream:
            print(f"deciwaves ds dump: line {lid!r} not found in catalog, skipping",
                  file=sys.stderr)
            missing += 1
            continue
        dst = os.path.join(a.out, f"{lid}.wav")
        try:
            wav_path, _dur = clip_wav(idx, stream, cache_dir)
            if os.path.abspath(wav_path) != os.path.abspath(dst):
                shutil.copyfile(wav_path, dst)
            ok += 1
        except ClipError as exc:
            print(f"deciwaves ds dump: line {lid!r} decode failed: {exc}", file=sys.stderr)
            errors += 1

    print(f"deciwaves ds dump: {ok} ok, {errors} errors, {missing} missing -> {a.out}")
    return 0 if errors == 0 else 1
