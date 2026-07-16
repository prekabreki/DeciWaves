"""Batch-extract Forbidden West English dialogue clips via the fast path.

Resolves every fast-path-provable English line (:mod:`engine.pack.fw_fast_extract`),
reads its self-describing RIFF/ATRAC9 clip from the package stream store, and
decodes it to a WAV with VGAudio. **Resumable** (skips line_ids already in the
manifest / processed log) and **fail-soft** (per-line errors logged, the run
never aborts) -- mirrors the HZD catalog batch conventions
(``engine.catalog_io.done_core_paths`` / ``processed_core_paths``).

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
``engine`` later.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from deciwaves.engine.atomic_io import atomic_write
from deciwaves.engine.parallel import default_jobs, ordered_parallel
from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore
from deciwaves.engine.pack.fw_fast_extract import iter_english_lines
from deciwaves.engine.tool_paths import resolve

MANIFEST_COLS = ["line_id", "group_id", "lssr_index", "file_index", "offset", "clip_bytes", "wav"]


class DecodeError(Exception):
    pass


def decode_clip(clip_bytes: bytes, wav_path: str, vgaudio: str = None) -> None:
    """Decode a self-describing RIFF/ATRAC9 *clip_bytes* to *wav_path* via VGAudio.

    FW dialogue clips are already plain ATRAC9 RIFF (no Wwise wrapper), so the
    bytes are written straight to a temp ``.at9`` and converted -- no trim.
    """
    if vgaudio is None:
        vgaudio = resolve("DECIWAVES_VGAUDIO", "VGAudioCli")
    with tempfile.NamedTemporaryFile(suffix=".at9", delete=False) as t:
        t.write(clip_bytes)
        tmp = t.name

    def _run(out):
        # atomic_write: VGAudio targets a tmp path moved into place only on
        # success, so a crash mid-decode never leaves a truncated .wav that a
        # later resume would trust, and concurrent extract workers can't
        # half-write a shared path (see engine.atomic_io).
        r = subprocess.run([vgaudio, "-i", tmp, "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out):
            raise DecodeError(f"VGAudioCli failed: {r.stderr.strip()}")

    try:
        atomic_write(wav_path, _run)
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
            vgaudio: str = None, jobs: int | None = None) -> ExtractStats:
    """Run the fast-path batch extraction. Returns counts. Idempotent/resumable.

    ``jobs`` reads+decodes that many clips concurrently (each a VGAudio
    subprocess); ``None`` -> ``min(8, cpu_count)``, ``1`` -> the old serial loop.
    Only the per-clip read+decode runs in workers; the manifest/processed/errors
    appends, the resume `done` skip and every ``stats`` counter are all touched on
    the calling thread, in line order (via engine.parallel.ordered_parallel), so
    the three output files are byte-identical to the serial run and need no lock.
    A clip's line_id is written to the processed log only *after* its worker
    returned -- i.e. after its WAV is fully on disk (atomic decode) -- so a crash
    mid-pool never records a not-yet-finished clip as done.
    """
    if vgaudio is None:
        vgaudio = resolve("DECIWAVES_VGAUDIO", "VGAudioCli")
    if jobs is None:
        jobs = default_jobs()
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

    def _todo():
        # Runs on the calling thread (ordered_parallel pulls it there): safe to
        # touch stats.resolved/skipped and the `done` set with no lock.
        for ln in iter_english_lines(graph):
            stats.resolved += 1
            if ln.line_id in done:
                stats.skipped += 1
                continue
            yield ln

    todo = _todo()
    if limit is not None:                      # cap NEW work, matching the old break
        todo = itertools.islice(todo, limit)

    def _work(ln):
        # Worker thread: read the clip and (optionally) decode it to its own
        # unique per-line WAV path. Returns a result record -- never raises for a
        # per-line failure, so the pool keeps running and the main thread does the
        # fail-soft logging in order.
        wav_rel = os.path.join("audio", f"{ln.line_id}.wav")
        try:
            clip = store.read_riff_clip(ln.locator.file_index, ln.locator.offset)
            if decode:
                decode_clip(clip, os.path.join(out_dir, wav_rel), vgaudio)
            row = {
                "line_id": ln.line_id, "group_id": ln.group_id,
                "lssr_index": ln.lssr_index, "file_index": ln.locator.file_index,
                "offset": ln.locator.offset, "clip_bytes": len(clip),
                "wav": wav_rel,
            }
            return ln, row, None
        except Exception as exc:  # fail-soft: reported by the main thread below
            return ln, None, f"{type(exc).__name__}: {exc}"

    new_manifest = not os.path.isfile(manifest_path) or os.path.getsize(manifest_path) == 0
    with open(manifest_path, "a", newline="", encoding="utf-8") as mf, \
            open(processed_path, "a", encoding="utf-8") as pf, \
            open(errors_path, "a", encoding="utf-8") as ef:
        writer = csv.DictWriter(mf, fieldnames=MANIFEST_COLS)
        if new_manifest:
            writer.writeheader()
        for ln, row, err in ordered_parallel(todo, _work, jobs):
            if err is None:
                writer.writerow(row)
                stats.ok += 1
            else:
                ef.write(f"{ln.line_id}\t{err}\n")
                stats.failed += 1
            pf.write(ln.line_id + "\n")   # recorded done only after the WAV is on disk
            if stats.ok % 50 == 0:
                mf.flush(); pf.flush(); ef.flush()
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
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="number of clips to read+decode concurrently (each spawns "
                         f"one VGAudioCli). Default min(8, cpu_count)={default_jobs()}; "
                         "--jobs 1 forces the old serial extract")
    a = ap.parse_args(argv)
    stats = extract(a.package, a.out_dir, limit=a.limit, decode=not a.no_decode,
                    jobs=a.jobs)
    msg = (f"resolved={stats.resolved} ok={stats.ok} skipped={stats.skipped} "
           f"failed={stats.failed}")
    if stats.failed:
        errors_path = os.path.join(a.out_dir, "extract-errors.log")
        msg += f" (see {errors_path})"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
