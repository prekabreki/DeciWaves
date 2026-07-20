"""FW dump: copy selected line ids from the existing extracted WAV pool.

FW's extract stage already produces WAVs under ``out/fw/audio/<line_id>.wav``,
so this stage copies those (plus the clip-index manifest) to a user-chosen dir.

    deciwaves fw dump --ids <ids.txt> --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil


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
    ap = argparse.ArgumentParser(description="FW: copy selected line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with one line_id per line")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--audio-dir", default="out/fw/audio",
                    help="extracted WAV directory (default: out/fw/audio)")
    ap.add_argument("--manifest", default="out/fw/clip-index.csv",
                    help="extract manifest CSV (default: out/fw/clip-index.csv)")
    a = ap.parse_args(argv)

    ids = [ln.strip() for ln in open(a.ids) if ln.strip()]
    if not ids:
        print("dump: ids file is empty -- nothing to do")
        return 0

    manifest_ids: set[str] = set()
    if os.path.isfile(a.manifest):
        with open(a.manifest, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                lid = r.get("line_id", "")
                if lid:
                    manifest_ids.add(lid)

    os.makedirs(a.out, exist_ok=True)

    unknown = 0
    failed = 0
    ok = 0
    used_names: set[str] = set()

    for line_id in ids:
        wav_src = os.path.join(a.audio_dir, f"{line_id}.wav")
        if not os.path.isfile(wav_src):
            if line_id in manifest_ids:
                print(f"dump: WARNING - {line_id}: manifest entry exists but WAV file not found")
            else:
                print(f"dump: WARNING - unknown line_id: {line_id}")
            unknown += 1
            continue

        try:
            safe = _safe_name(line_id, used_names)
            used_names.add(safe)
            dst = os.path.join(a.out, f"{safe}.wav")
            if os.path.abspath(wav_src) != os.path.abspath(dst):
                shutil.copyfile(wav_src, dst)
            ok += 1
        except Exception as exc:
            print(f"dump: WARNING - {line_id}: copy failed: {exc}")
            failed += 1

    print(f"dump: {ok} ok, {failed} failed, {unknown} unknown")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
