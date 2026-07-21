"""HZD dump: decode selected line ids to WAV via clip-index + decode_wem_to_wav.

Requires bind artifacts (asr-manifest.csv + clip-index.csv). Pre-bind
exit with a clear "needs bind" message (non-zero) rather than a traceback.
"""
from __future__ import annotations

import argparse
import csv
import os

from deciwaves.cli import config as cli_config
from deciwaves.engine.pack.hzd_package import HzdPackage
from deciwaves.games.hzd.atrac9 import decode_wem_to_wav
from deciwaves.games.hzd.catalog import load_hzd_manifest_join
from deciwaves.games.hzd.profile import VOICE_ARCHIVE, hzd_package_error


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


def _needs_bind(manifest_path: str) -> str | None:
    """Return an error message if bind has not been run, else None."""
    if not os.path.isfile(manifest_path):
        return (f"HZD bind manifest not found at {manifest_path}. "
                f"Run `deciwaves hzd bind` first.")
    try:
        with open(manifest_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return (f"HZD bind manifest at {manifest_path} is unreadable. "
                f"Re-run `deciwaves hzd bind`.")
    if not rows:
        return (f"HZD bind manifest at {manifest_path} is empty -- "
                f"bind produced no results. Run `deciwaves hzd bind` first.")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Decode HZD line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with line_ids (one per line)")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--package", default=None,
                    help="HZDR package directory (reads from config if omitted)")
    ap.add_argument("--manifest", default="out/hzd/asr-manifest.csv",
                    help="bind manifest CSV (default out/hzd/asr-manifest.csv)")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv",
                    help="clip-index CSV (default out/hzd/clip-index.csv)")
    a = ap.parse_args(argv)

    pkg = a.package
    if not pkg:
        cfg = cli_config.load()
        pkg = cfg.get("hzd_package", "")
    if not pkg:
        print("HZD package not configured. Pass --package or run `deciwaves setup`.")
        return 1
    err = hzd_package_error(pkg)
    if err:
        print(err)
        return 1

    msg = _needs_bind(a.manifest)
    if msg:
        print(msg)
        return 1

    clip_index_path = a.clip_index
    if not os.path.isfile(clip_index_path):
        print(f"HZD clip-index not found at {clip_index_path}. "
              f"Run `deciwaves hzd clip-index` first.")
        return 1

    line_to_clip, clip_coords = load_hzd_manifest_join(a.manifest, clip_index_path)
    if not line_to_clip:
        print(f"No line-to-clip bindings found in {a.manifest}.")
        return 1

    ids = _load_ids(a.ids)
    if not ids:
        print("No line ids to process.")
        return 0

    hzd_pkg = HzdPackage(pkg)
    dsar = hzd_pkg.dsar_for(VOICE_ARCHIVE)
    os.makedirs(a.out, exist_ok=True)

    used: set[str] = set()
    ok = skipped = 0
    for lid in ids:
        clip_row_str = line_to_clip.get(lid)
        if clip_row_str is None:
            print(f"WARNING: line_id {lid!r} not found in bind manifest -- skipping")
            skipped += 1
            continue
        try:
            cr = int(clip_row_str)
        except (TypeError, ValueError):
            print(f"WARNING: line_id {lid!r} has invalid clip_row {clip_row_str!r} -- skipping")
            skipped += 1
            continue
        coords = clip_coords.get(cr)
        if coords is None:
            print(f"WARNING: no clip coordinates for line_id {lid!r} (clip_row {cr}) -- skipping")
            skipped += 1
            continue
        safe = _safe_name(lid, used)
        used.add(safe)
        dst = os.path.join(a.out, f"{safe}.wav")
        try:
            wem_bytes = dsar.read(*coords)
            decode_wem_to_wav(wem_bytes, dst)
            ok += 1
        except Exception as exc:
            print(f"WARNING: could not decode line_id {lid!r}: {exc} -- skipping")
            skipped += 1

    print(f"dump: {ok} ok, {skipped} skipped -> {a.out}")
    return 1 if skipped and not ok else 0
