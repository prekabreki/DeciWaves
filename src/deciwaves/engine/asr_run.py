"""Game-agnostic ASR transcript orchestration: resumable, fail-soft per-clip
transcription loop.

Runs an injected ``transcribe_fn`` over every pending clip in a clip-index CSV
and appends ``(line_id, transcript, speech_ratio)`` rows to a transcripts cache.
Skips already-cached ``line_id``\\s, logs per-clip errors without aborting, and
flushes incrementally so a crash keeps progress.

This module is imported by per-game ``asr_run`` modules (``games/fw/asr_run.py``,
``games/ds2/asr_run.py``) which keep only their own ``main()`` CLI and any
game-specific initialisation (rosters, file-index filters).
"""

from __future__ import annotations

import csv
from pathlib import Path

TRANSCRIPT_COLS = ["line_id", "transcript", "speech_ratio"]


def load_clip_index(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_done_ids(transcripts_csv: str | Path) -> set[str]:
    p = Path(transcripts_csv)
    if not p.exists():
        return set()
    with p.open(newline="", encoding="utf-8-sig") as f:
        return {row["line_id"] for row in csv.DictReader(f)}


def run(clip_rows, transcripts_csv, audio_root, transcribe_fn, log=print):
    """Transcribe each pending clip and append `(line_id, transcript, speech_ratio)`.

    `transcribe_fn(wav_path)` returns an object with `.text` and `.speech_ratio`.
    `audio_root` is the directory the clip-index `wav` paths are relative to
    (i.e. `out/<game>`). Returns `(n_ok, n_err)`.
    """
    transcripts_csv = Path(transcripts_csv)
    audio_root = Path(audio_root)
    done = read_done_ids(transcripts_csv)
    pending = [r for r in clip_rows if r["line_id"] not in done]
    transcripts_csv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not transcripts_csv.exists() or transcripts_csv.stat().st_size == 0

    n_ok = n_err = 0
    with transcripts_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRANSCRIPT_COLS)
        if new_file:
            w.writeheader()
        for r in pending:
            wav = audio_root / r["wav"]
            try:
                t = transcribe_fn(str(wav))
                w.writerow({"line_id": r["line_id"], "transcript": t.text,
                            "speech_ratio": round(t.speech_ratio, 4)})
                f.flush()
                n_ok += 1
            except Exception as e:  # fail-soft: log and keep going
                log(f"ERROR {r['line_id']}: {e}")
                n_err += 1
    return n_ok, n_err
