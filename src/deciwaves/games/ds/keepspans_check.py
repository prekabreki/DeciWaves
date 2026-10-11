"""Find cutscene tracks the keep-spans manifest drops while they still carry audio.

`ds/cutscene-keepspans.csv` is WhisperX output that the render consumes blind: a
`dropped=1` row never renders and nothing reports it. Where ASR misses quiet words
the track vanishes -- `sq_cs10_s00700` (Sam's "Louise.", the game's final beat)
never rendered in any reel. This stage decodes every `dropped=1` track, downmixes it
the way the render does, and runs a level gate over it (games.ds.speech_trim).

Check (default): report every dropped row whose track has audio above the gate.
Rows a human has listened to and accepted as dropped (title cards that only
breathe, private-room asides) live in the packaged `ds/cutscene-keepspans-reviewed.csv`
and are reported but do not fail. Exits 1 while any unreviewed row remains.

Emit (`--emit LINE_ID ...`): write a copy of the manifest with gate spans for the
named rows only. A named row must be `dropped=1`, and its replacement must keep
more audio than the original in at most MAX_SPANS spans, or it is refused and left
unchanged. The packaged data is never modified; pass the copy to
`ds render --speech-trim`.

Read-only against the install. Decoding needs vgmstream and ffmpeg.
"""
from __future__ import annotations

import csv
import os
import sys
import wave

import numpy as np

from deciwaves.games.ds.speech_trim import (
    format_spans, gate_spans, kept_seconds, parse_spans, refuse_replacement)


def read_mono(path):
    """(samples, rate) from a 16-bit PCM WAV: channels averaged, scaled to [-1, 1]."""
    with wave.open(path) as w:
        rate, chans, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got {8 * width}-bit")
    a = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if chans > 1:
        a = a.reshape(-1, chans).mean(axis=1)
    return a / 32768.0, rate


def check(rows, measure_fn, reviewed=frozenset()):
    """(flagged, errors) over keep-spans rows. Only `dropped=1` rows are measured;
    measure_fn(stream_path) -> (spans, total). `flagged` lists dicts with
    line_id, stream_path, total, kept, spans and `reviewed` (line_id in `reviewed`)
    for every dropped row whose gate spans are non-empty. `errors` lists
    (line_id, message) for tracks that could not be measured."""
    flagged, errors = [], []
    for r in rows:
        if r["dropped"] != "1":
            continue
        try:
            spans, total = measure_fn(r["stream_path"])
        except Exception as e:                       # report, keep checking the rest
            errors.append((r["line_id"], str(e)))
            continue
        if spans:
            flagged.append({"line_id": r["line_id"], "stream_path": r["stream_path"],
                            "total": total, "kept": kept_seconds(spans), "spans": spans,
                            "reviewed": r["line_id"] in reviewed})
    return flagged, errors


def emit(rows, names, measure_fn):
    """(patched_rows, applied, refused) for the line_ids in `names`. Returns a new
    list of row dicts; the input rows are not mutated. A named row is refused (and
    copied unchanged) when it is missing, not `dropped=1`, or its gate spans fail
    speech_trim.refuse_replacement. `applied` lists line_ids patched; `refused`
    lists (line_id, reason)."""
    names = list(dict.fromkeys(names))
    by_id = {r["line_id"]: r for r in rows}
    refused = [(n, "no such line_id in the manifest") for n in names if n not in by_id]
    replace, applied = {}, []
    for n in names:
        r = by_id.get(n)
        if r is None:
            continue
        if r["dropped"] != "1":
            refused.append((n, "not a dropped=1 row; the gate never touches healthy rows"))
            continue
        try:
            spans, total = measure_fn(r["stream_path"])
        except Exception as e:
            refused.append((n, f"could not measure: {e}"))
            continue
        why = refuse_replacement(spans, parse_spans(r["keep_spans"]))
        if why:
            refused.append((n, why))
            continue
        replace[n] = {**r, "keep_spans": format_spans(spans),
                      "speech_ratio": str(round(kept_seconds(spans) / total, 4)),
                      "dropped": "0"}
        applied.append(n)
    return [replace.get(r["line_id"], r) for r in rows], applied, refused


def load_reviewed(path):
    """line_id -> reason from a reviewed-dropped CSV (columns line_id, reason)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["line_id"]: r["reason"] for r in csv.DictReader(f)}


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def _report(flagged, errors, reviewed):
    for f in flagged:
        tag = f"reviewed: {reviewed[f['line_id']]}" if f["reviewed"] else "UNREVIEWED"
        print(f"  {f['line_id']:<30} {f['total']:7.1f}s track, {f['kept']:6.2f}s above gate "
              f"in {len(f['spans'])} span(s)  [{tag}]")
    for line_id, msg in errors:
        print(f"  {line_id:<30} ERROR {msg}")


def main(argv=None):
    import argparse
    from deciwaves import data
    ap = argparse.ArgumentParser(
        description="Report keep-spans rows dropped while their track still carries audio")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--keepspans", default=None,
                    help="keep-spans manifest to check; default = packaged ds/cutscene-keepspans.csv")
    ap.add_argument("--reviewed", default=None,
                    help="reviewed-dropped list; default = packaged ds/cutscene-keepspans-reviewed.csv")
    ap.add_argument("--cache", default="out/wav-cache")
    ap.add_argument("--emit", nargs="+", metavar="LINE_ID", default=None,
                    help="write gate spans for these dropped=1 rows (guarded) to --out")
    ap.add_argument("--out", default="out/cutscene-keepspans.patched.csv")
    args = ap.parse_args(argv)

    from deciwaves.engine import audio_clip
    from deciwaves.engine.pack.bin_index import PackIndex
    from deciwaves.engine.render import normalize_wav
    from deciwaves.engine.tool_paths import resolve

    keepspans = args.keepspans or str(data.packaged("ds/cutscene-keepspans.csv"))
    rows, fields = _read_csv(keepspans)
    idx = PackIndex(args.data_dir, args.oodle)
    vgmstream = resolve("DECIWAVES_VGMSTREAM", "vgmstream-cli")
    norm_dir = os.path.join(args.cache, "norm")

    def measure_fn(stream):
        # Downmix exactly as the render does, so the gate hears what a reel would.
        wav, _ = audio_clip.clip_wav(idx, stream, args.cache, vgmstream=vgmstream)
        return gate_spans(*read_mono(normalize_wav(wav, norm_dir)))

    if args.emit is not None:
        patched, applied, refused = emit(rows, args.emit, measure_fn)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(patched)
        for n in applied:
            r = next(p for p in patched if p["line_id"] == n)
            print(f"  {n:<30} patched: {r['keep_spans']} (speech_ratio {r['speech_ratio']})")
        for n, why in refused:
            print(f"  {n:<30} REFUSED: {why}")
        print(f"keepspans-check: patched {len(applied)}, refused {len(refused)} -> {args.out}")
        return 1 if refused else 0

    reviewed = load_reviewed(args.reviewed or str(data.packaged("ds/cutscene-keepspans-reviewed.csv")))
    flagged, errors = check(rows, measure_fn, reviewed=reviewed)
    _report(flagged, errors, reviewed)
    unreviewed = [f for f in flagged if not f["reviewed"]]
    dropped = sum(r["dropped"] == "1" for r in rows)
    print(f"keepspans-check: {dropped} dropped rows, {len(flagged)} carry audio above the gate "
          f"({len(unreviewed)} unreviewed), {len(errors)} errors")
    return 1 if unreviewed or errors else 0


if __name__ == "__main__":
    sys.exit(main())
