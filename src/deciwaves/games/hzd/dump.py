"""HZD dump stage: decode selected line IDs to WAV files.

Reads a file with one line_id per line, looks up the clip coordinates from
the ASR bind manifest and clip index, and decodes each to a WAV via
decode_wem_to_wav. Fails with a clear message if the bind artifacts are
absent (pre-bind guard).
"""
from __future__ import annotations

import os
import sys

from deciwaves.engine.pack.hzd_package import HzdPackage
from deciwaves.games.hzd.atrac9 import decode_wem_to_wav, Atrac9Error
from deciwaves.games.hzd.catalog import load_hzd_manifest_join
from deciwaves.games.hzd.profile import VOICE_ARCHIVE


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
    ap = argparse.ArgumentParser(description="HZD: decode selected clips to WAV files")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--manifest", default="out/hzd/asr-manifest.csv",
                    help="ASR bind manifest (default: out/hzd/asr-manifest.csv)")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv",
                    help="clip index (default: out/hzd/clip-index.csv)")
    ap.add_argument("--package", default="",
                    help="HZD package directory (or set hzd_package in config)")
    ap.add_argument("--out", default="out/hzd/dump", help="output directory for WAVs")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.manifest) or not os.path.isfile(a.clip_index):
        print("deciwaves hzd dump: bind artifacts not found -- run `deciwaves hzd bind` first",
              file=sys.stderr)
        print(f"  missing: {a.manifest} or {a.clip_index}", file=sys.stderr)
        return 1

    ids = _read_ids(a.ids)
    if not ids:
        print("deciwaves hzd dump: no line IDs in --ids file", file=sys.stderr)
        return 1

    line_to_clip, clip_coords = load_hzd_manifest_join(a.manifest, a.clip_index)
    if not line_to_clip:
        print("deciwaves hzd dump: no lines in manifest -- run `deciwaves hzd bind` first",
              file=sys.stderr)
        return 1

    pkg_dir = a.package or os.environ.get("DECIWAVES_HZD_PACKAGE", "")
    if not pkg_dir or not os.path.isdir(pkg_dir):
        print("deciwaves hzd dump: HZD package directory not found -- "
              "pass --package or configure hzd_package via `deciwaves setup`",
              file=sys.stderr)
        return 1

    os.makedirs(a.out, exist_ok=True)
    pkg = HzdPackage(pkg_dir)
    dsar = pkg.dsar_for(VOICE_ARCHIVE)

    ok = 0
    missing = 0
    errors = 0
    for lid in ids:
        clip_row = line_to_clip.get(lid)
        if clip_row is None:
            print(f"deciwaves hzd dump: line {lid!r} not found in manifest, skipping",
                  file=sys.stderr)
            missing += 1
            continue
        try:
            cr = int(clip_row)
        except (TypeError, ValueError):
            print(f"deciwaves hzd dump: line {lid!r} has invalid clip row {clip_row!r}",
                  file=sys.stderr)
            errors += 1
            continue
        coords = clip_coords.get(cr)
        if coords is None:
            print(f"deciwaves hzd dump: no clip coordinates for line {lid!r} (clip row {cr})",
                  file=sys.stderr)
            missing += 1
            continue
        dst = os.path.join(a.out, f"{lid}.wav")
        try:
            wem = dsar.read(*coords)
            decode_wem_to_wav(wem, dst)
            ok += 1
        except (Atrac9Error, OSError) as exc:
            print(f"deciwaves hzd dump: line {lid!r} decode failed: {exc}", file=sys.stderr)
            errors += 1

    print(f"deciwaves hzd dump: {ok} ok, {errors} errors, {missing} missing -> {a.out}")
    return 0 if errors == 0 else 1
