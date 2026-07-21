"""FW dump: copy selected line ids to WAV from already-extracted audio."""
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


def _load_ids(path: str) -> list[str]:
    lines = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                lines.append(ln)
    return lines


def _resolve_wav_path(audio_root: str, wav_rel: str | None) -> str | None:
    """Resolve a manifest ``wav`` (relative to ``out/fw/``) to an absolute path."""
    if not wav_rel:
        return None
    return os.path.normpath(os.path.join(audio_root, wav_rel))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Copy FW line ids to WAV")
    ap.add_argument("--ids", required=True, help="file with line_ids (one per line)")
    ap.add_argument("--out", required=True, help="output directory for WAV files")
    ap.add_argument("--audio-root", default="out/fw",
                    help="FW audio root directory (default out/fw)")
    ap.add_argument("--manifest", default=None,
                    help="manifest CSV (default: auto-detect between "
                         "full-reel-manifest.csv / subtitle-manifest-full.csv / clip-index.csv)")
    a = ap.parse_args(argv)

    root = a.audio_root
    manifest = a.manifest
    if not manifest:
        for name in ("full-reel-manifest.csv", "subtitle-manifest-full.csv", "clip-index.csv"):
            candidate = os.path.join(root, name)
            if os.path.isfile(candidate):
                manifest = candidate
                break
    if not manifest or not os.path.isfile(manifest):
        print(f"No FW manifest found under {root}. Run `deciwaves fw extract` first.")
        return 1

    line_to_wav: dict[str, str] = {}
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lid = row.get("line_id", "")
            if not lid:
                continue
            wav_rel = row.get("wav") or ""
            wav_path = _resolve_wav_path(root, wav_rel)
            if wav_path:
                line_to_wav[lid] = wav_path

    if not line_to_wav:
        print(f"No line_id -> wav mappings found in {manifest}.")
        return 1

    ids = _load_ids(a.ids)
    if not ids:
        print("No line ids to process.")
        return 0

    os.makedirs(a.out, exist_ok=True)
    used: set[str] = set()
    ok = skipped = 0
    for lid in ids:
        src = line_to_wav.get(lid)
        if not src:
            print(f"WARNING: line_id {lid!r} not found in manifest -- skipping")
            skipped += 1
            continue
        if not os.path.isfile(src):
            print(f"WARNING: WAV file for line_id {lid!r} not found at {src} -- skipping")
            skipped += 1
            continue
        safe = _safe_name(lid, used)
        used.add(safe)
        dst = os.path.join(a.out, f"{safe}.wav")
        shutil.copy2(src, dst)
        ok += 1

    print(f"dump: {ok} ok, {skipped} skipped -> {a.out}")
    return 1 if skipped and not ok else 0
