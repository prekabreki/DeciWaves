"""Batch-extract Forbidden West English dialogue clips via the fast path.

Resolves every fast-path-provable English line (:mod:`engine.pack.fw_fast_extract`),
reads its self-describing RIFF/ATRAC9 clip from the package stream store, and
decodes it to a WAV with VGAudio. **Resumable** (skips line_ids already in the
manifest / processed log) and **fail-soft** (per-line errors logged, the run
never aborts) -- mirrors the HZD catalog batch conventions
(``engine.catalog.done_core_paths`` / ``processed_core_paths``).

Output (all gitignored under ``out/fw/``)::

    out/fw/audio/<line_id>.wav         decoded clips
    out/fw/clip-index.csv              manifest (see MANIFEST_COLS)
    out/fw/clip-index-processed.txt    every line_id reaching a terminal outcome
    out/fw/extract-errors.log          per-line failures (line_id \\t error)

Speaker / subtitle / story order are added downstream (ASR vs
``docs/forbidden_west_gamescript.md`` -- the proven HZD path). FW clips are plain
RIFF/ATRAC9 (unlike HZD's Wwise ``.wem``), so decode is a direct VGAudio call
with no trim. That codec decoder is intentionally duplicated rather than imported
from ``games.hzd`` to keep games decoupled; it could be promoted to
``engine`` later (issue #10).
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from engine.pack.fw_streaming_graph import StreamingGraph
from engine.pack.fw_stream import FwStreamStore
from engine.pack.fw_fast_extract import iter_english_lines

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VGAUDIO = os.path.join(_REPO, "vendor", "vgaudio", "VGAudioCli.exe")

MANIFEST_COLS = ["line_id", "group_id", "lssr_index", "file_index", "offset", "clip_bytes", "wav"]


class DecodeError(Exception):
    pass


def decode_clip(clip_bytes: bytes, wav_path: str, vgaudio: str = VGAUDIO) -> None:
    """Decode a self-describing RIFF/ATRAC9 *clip_bytes* to *wav_path* via VGAudio.

    FW dialogue clips are already plain ATRAC9 RIFF (no Wwise wrapper), so the
    bytes are written straight to a temp ``.at9`` and converted -- no trim.
    """
    with tempfile.NamedTemporaryFile(suffix=".at9", delete=False) as t:
        t.write(clip_bytes)
        tmp = t.name
    try:
        r = subprocess.run([vgaudio, "-i", tmp, "-o", wav_path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise DecodeError(f"VGAudioCli failed: {r.stderr.strip()}")
    finally:
        os.unlink(tmp)


def load_done(manifest_path: str, processed_path: str) -> set[str]:
    """line_ids already extracted (manifest rows) or terminally processed
    (failures/skips). Union = skip on resume, mirroring the HZD pattern."""
    done: set[str] = set()
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["line_id"])
    if os.path.isfile(processed_path):
        with open(processed_path, "r", encoding="utf-8") as f:
            done.update(ln.strip() for ln in f if ln.strip())
    return done


@dataclass
class ExtractStats:
    resolved: int = 0   # total fast-path lines
    skipped: int = 0    # already done (resume)
    ok: int = 0         # newly extracted this run
    failed: int = 0     # per-line failures this run


def extract(package_dir: str, out_dir: str = "out/fw", *,
            limit: int | None = None, decode: bool = True,
            vgaudio: str = VGAUDIO) -> ExtractStats:
    """Run the fast-path batch extraction. Returns counts. Idempotent/resumable."""
    # Fail fast on the dominant whole-environment failure: a missing/misconfigured
    # VGAudio. Without this, the per-line except below would log every one of the
    # ~61k lines as a failure AND mark each "processed", silently poisoning resume so
    # a re-run after fixing the path extracts nothing. Checked before the package load
    # so it raises immediately and writes nothing. (Per-line transient errors — e.g. a
    # locked file — are a narrower, separate concern; see the audit follow-up.)
    if decode and not os.path.isfile(vgaudio):
        raise DecodeError(f"VGAudio not found at {vgaudio!r} (decode=True). "
                          f"Pass decode=False to resolve/manifest only, or fix the path.")
    audio_dir = os.path.join(out_dir, "audio")
    manifest_path = os.path.join(out_dir, "clip-index.csv")
    processed_path = os.path.join(out_dir, "clip-index-processed.txt")
    errors_path = os.path.join(out_dir, "extract-errors.log")
    os.makedirs(audio_dir, exist_ok=True)

    graph = StreamingGraph.from_file(os.path.join(package_dir, "streaming_graph.core"))
    store = FwStreamStore(package_dir, graph.files)
    done = load_done(manifest_path, processed_path)
    stats = ExtractStats()

    new_manifest = not os.path.isfile(manifest_path)
    with open(manifest_path, "a", newline="", encoding="utf-8") as mf, \
            open(processed_path, "a", encoding="utf-8") as pf, \
            open(errors_path, "a", encoding="utf-8") as ef:
        writer = csv.DictWriter(mf, fieldnames=MANIFEST_COLS)
        if new_manifest:
            writer.writeheader()
        for ln in iter_english_lines(graph):
            stats.resolved += 1
            if ln.line_id in done:
                stats.skipped += 1
                continue
            wav_rel = os.path.join("audio", f"{ln.line_id}.wav")
            try:
                clip = store.read_riff_clip(ln.locator.file_index, ln.locator.offset)
                if decode:
                    decode_clip(clip, os.path.join(out_dir, wav_rel), vgaudio)
                writer.writerow({
                    "line_id": ln.line_id, "group_id": ln.group_id,
                    "lssr_index": ln.lssr_index, "file_index": ln.locator.file_index,
                    "offset": ln.locator.offset, "clip_bytes": len(clip),
                    "wav": wav_rel,
                })
                stats.ok += 1
            except Exception as exc:  # fail-soft: log, mark done, never abort
                ef.write(f"{ln.line_id}\t{type(exc).__name__}: {exc}\n")
                stats.failed += 1
            pf.write(ln.line_id + "\n")
            if stats.ok % 50 == 0:
                mf.flush(); pf.flush(); ef.flush()
            if limit is not None and (stats.ok + stats.failed) >= limit:
                break
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FW fast-path English clip extractor")
    ap.add_argument("--package", required=True,
                    help="FW package dir containing streaming_graph.core")
    ap.add_argument("--out-dir", default="out/fw")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N new lines (smoke test)")
    ap.add_argument("--no-decode", action="store_true",
                    help="resolve + manifest only, skip WAV decode")
    a = ap.parse_args(argv)
    stats = extract(a.package, a.out_dir, limit=a.limit, decode=not a.no_decode)
    print(f"resolved={stats.resolved} ok={stats.ok} skipped={stats.skipped} "
          f"failed={stats.failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
