"""DS2 ASR pass (transcript stage): transcribe every extracted clip into a
match-key transcript cache.

Resumable (skips `line_id`s already cached) and fail-soft (per-clip errors are
logged, never abort the run; a failed clip is simply absent and retried next
run). Rows are appended and flushed incrementally so a crash keeps progress.

The transcription itself is injected (`transcribe_fn`) so the orchestration is
testable without the GPU stack; `main()` wires the real WhisperX model.
"""

from __future__ import annotations

import csv
from pathlib import Path

TRANSCRIPT_COLS = ["line_id", "transcript", "speech_ratio"]


def load_clip_index(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def select_clips(rows, limit=0):
    """Subset clip rows by a count cap."""
    return rows[:limit] if limit else rows


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
    (i.e. `out/ds2`). Returns `(n_ok, n_err)`.
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


def main(argv=None):
    import argparse

    from deciwaves.engine import asr

    ap = argparse.ArgumentParser(description="DS2 ASR transcript pass")
    ap.add_argument("--clip-index", default="out/ds2/clip-index.csv")
    ap.add_argument("--audio-root", default="out/ds2",
                    help="dir the clip-index 'wav' paths are relative to")
    ap.add_argument("--out", default="out/ds2/transcripts.csv")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--language", default="en",
                    help="pin transcription language (DS2 clips are all en); '' to auto-detect")
    ap.add_argument("--limit", type=int, default=0, help="cap clips (0 = all)")
    a = ap.parse_args(argv)

    rows = select_clips(load_clip_index(a.clip_index), limit=a.limit)
    model = asr.load_model(a.model)
    print(f"clips={len(rows)} model={a.model}")

    lang = a.language or None
    n_ok, n_err = run(
        rows, a.out, a.audio_root,
        transcribe_fn=lambda w: asr.transcribe(w, model, batch_size=a.batch_size, language=lang),
    )
    print(f"transcribed ok={n_ok} err={n_err} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
