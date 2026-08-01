"""DS2 ASR pass (transcript stage): transcribe every extracted clip into a
match-key transcript cache.

Resumable (skips `line_id`s already cached) and fail-soft (per-clip errors are
logged, never abort the run; a failed clip is simply absent and retried next
run). Rows are appended and flushed incrementally so a crash keeps progress.

The transcription itself is injected (`transcribe_fn`) so the orchestration is
testable without the GPU stack; `main()` wires the real WhisperX model.
"""

from __future__ import annotations

from deciwaves.engine.asr_run import TRANSCRIPT_COLS, load_clip_index, read_done_ids, run  # noqa: F401


def select_clips(rows, limit=0):
    """Subset clip rows by a count cap."""
    return rows[:limit] if limit else rows


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
