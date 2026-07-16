"""Stage 1 of DS cutscene speech-region trim: transcribe each resolved
cutscene whole-scene track, derive keep-spans, and write out/cutscene-keepspans.csv.

Runs in the GPU .venv-asr (WhisperX). Resumable (skips streams already in the
output CSV) and fail-soft (per-track errors logged, run never aborts). The render
consumes the CSV with no GPU dependency (engine.render --speech-trim).
"""
from __future__ import annotations

import csv
import os

from deciwaves.engine.speech_trim import keep_spans, format_spans

FIELDS = ["stream_path", "line_id", "speech_ratio", "keep_spans", "dropped"]


def run(rows, decode_fn, transcribe_fn, done=frozenset(),
        pad=0.35, merge_gap=0.5, min_speech=1.0):
    """(results, errors) over resolved cutscene-track rows. decode_fn(stream) ->
    (wav, total_seconds); transcribe_fn(wav) -> [segment dict]. Injectable for
    tests (no GPU/install). See module docstring for the contract."""
    results, errors = [], []
    for r in rows:
        stream = (r.get("voice_track_stream") or "").strip()
        if r.get("status") != "resolved" or not stream or stream in done:
            continue
        try:
            wav, total = decode_fn(stream)
            segs = transcribe_fn(wav)
            pairs = [(s["start"], s["end"]) for s in segs]
            spans, dropped = keep_spans(pairs, total, pad=pad, merge_gap=merge_gap,
                                        min_speech=min_speech)
            speech = sum(b - a for a, b in pairs)
            results.append({
                "stream_path": stream,
                "line_id": f"{r['scene']}#track{r['track_index']}",
                "speech_ratio": round(min(1.0, speech / total) if total else 0.0, 4),
                "keep_spans": format_spans(spans),
                "dropped": int(dropped),
            })
        except Exception as e:                       # fail-soft: log, keep going
            errors.append((stream, str(e)))
    return results, errors


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _done_streams(out_path):
    if not os.path.isfile(out_path):
        return set()
    with open(out_path, newline="", encoding="utf-8") as f:
        return {r["stream_path"] for r in csv.DictReader(f)}


def _append_rows(out_path, results):
    new = not os.path.isfile(out_path)
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(results)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="DS cutscene speech-region keep-spans")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--tracks", default="out/cutscene_tracks.csv")
    ap.add_argument("--out", default="out/cutscene-keepspans.csv")
    ap.add_argument("--cache", default="out/wav-cache")
    ap.add_argument("--errors", default="out/cutscene-trim-errors.log")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--pad", type=float, default=0.35)
    ap.add_argument("--merge-gap", type=float, default=0.5)
    ap.add_argument("--min-speech", type=float, default=1.0)
    ap.add_argument("--scenes", default="", help="comma-separated scene substrings to limit to (validation)")
    args = ap.parse_args(argv)

    from deciwaves.engine import asr, audio_clip
    from deciwaves.engine.pack.bin_index import PackIndex

    idx = PackIndex(args.data_dir, args.oodle)
    model = asr.load_model(args.model)
    rows = _read_rows(args.tracks)
    if args.scenes:
        keys = tuple(s for s in args.scenes.split(",") if s)
        rows = [r for r in rows if any(k in r.get("scene", "") for k in keys)]
    done = _done_streams(args.out)

    def decode_fn(stream):
        wav, dur = audio_clip.clip_wav(idx, stream, args.cache)
        return wav, dur

    def transcribe_fn(wav):
        return asr.transcribe_segments(wav, model)

    results, errors = run(rows, decode_fn, transcribe_fn, done=done,
                          pad=args.pad, merge_gap=args.merge_gap, min_speech=args.min_speech)
    _append_rows(args.out, results)
    with open(args.errors, "w", encoding="utf-8") as f:
        for stream, msg in errors:
            f.write(f"{stream}\t{msg}\n")
    dropped = sum(r["dropped"] for r in results)
    print(f"cutscene-trim: {len(results)} tracks ({dropped} dropped pure-grunt), "
          f"{len(errors)} errors -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
