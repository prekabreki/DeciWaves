"""FW dump stage: copy selected already-decoded WAV files.

FW dialogue clips are already decoded to WAV by the extract stage; this
stage copies the selected WAV files from the existing audio directory to
a clean output directory. Reads the manifest CSV to map line_ids to WAV
paths.
"""
from __future__ import annotations

import csv
import os
import shutil
import sys


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
    ap = argparse.ArgumentParser(description="FW: copy selected WAV files to output directory")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--manifest", default="out/fw/manifest.csv",
                    help="FW manifest CSV (default: out/fw/manifest.csv)")
    ap.add_argument("--audio-dir", default="out/fw",
                    help="base directory containing the audio files (default: out/fw)")
    ap.add_argument("--out", default="out/fw/dump", help="output directory for WAVs")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.manifest):
        print(f"deciwaves fw dump: manifest not found at {a.manifest}", file=sys.stderr)
        return 1

    ids = _read_ids(a.ids)
    if not ids:
        print("deciwaves fw dump: no line IDs in --ids file", file=sys.stderr)
        return 1

    id_to_wav: dict[str, str] = {}
    with open(a.manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lid = row.get("line_id", "")
            wav = row.get("wav", "")
            if lid and wav:
                id_to_wav[lid] = wav

    os.makedirs(a.out, exist_ok=True)
    ok = 0
    missing = 0
    errors = 0
    for lid in ids:
        wav_rel = id_to_wav.get(lid)
        if not wav_rel:
            print(f"deciwaves fw dump: line {lid!r} not found in manifest, skipping",
                  file=sys.stderr)
            missing += 1
            continue
        src = os.path.join(a.audio_dir, wav_rel)
        if not os.path.isfile(src):
            print(f"deciwaves fw dump: WAV for line {lid!r} not found at {src}, skipping",
                  file=sys.stderr)
            errors += 1
            continue
        dst = os.path.join(a.out, f"{lid}.wav")
        try:
            shutil.copyfile(src, dst)
            ok += 1
        except OSError as exc:
            print(f"deciwaves fw dump: line {lid!r} copy failed: {exc}", file=sys.stderr)
            errors += 1

    print(f"deciwaves fw dump: {ok} ok, {errors} errors, {missing} missing -> {a.out}")
    return 0 if errors == 0 else 1
