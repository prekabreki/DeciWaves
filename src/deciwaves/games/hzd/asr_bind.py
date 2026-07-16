"""MVP orchestration for ASR content-binding: decode -> transcribe -> match -> manifest."""
from __future__ import annotations
import argparse
import csv
import os
import sys
import tempfile
import wave
from deciwaves.engine import asr
from deciwaves.engine.pack.fw_package import FwPackage
from deciwaves.games.hzd import match
from deciwaves.games.hzd.atrac9 import Atrac9Error, decode_wem_to_wav
from deciwaves.games.hzd.binding import build_buckets, relevant_buckets, structural_binds
from deciwaves.games.hzd.catalog import load_catalog_dict
from deciwaves.games.hzd.profile import VOICE_ARCHIVE as ARCHIVE

# Single source of truth for the incremental checkpoint sidecar's default path --
# also read by cli/run.py's chained `hzd run` to decide whether to pass a prior
# run's sidecar back in via --transcripts (see _load_transcripts_sidecar below).
DEFAULT_TRANSCRIPTS_OUT = "out/hzd/asr-transcripts.csv"
MANIFEST_COLS = ["clip_row", "offset", "line_id", "speaker_name", "subtitle_en", "scene", "tier", "score", "transcript"]
# Incremental transcript checkpoint sidecar: exactly the columns the --transcripts reuse
# path below consumes (r["clip_row"], r.get("transcript", "")) -- a prior full manifest
# (MANIFEST_COLS, a superset) also satisfies this reader, so either can be passed to
# --transcripts.
TRANSCRIPTS_COLS = ["clip_row", "transcript"]

# Circuit breaker (Task 14b / issue #20 review): if the first BREAKER_K clips processed
# in a run ALL fail with zero successes, that looks like a broken environment (missing
# ffmpeg/decoder binary, a bad WhisperX arg, ...) rather than per-clip corruption -- keep
# going would just burn the whole run logging N identical failures. Disarmed permanently
# after the first success; failures after that keep the existing per-clip fail-soft.
BREAKER_K = 5


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_transcripts_sidecar(path):
    """Load a transcript sidecar's (or a prior manifest's) clip_row/transcript columns
    for --transcripts reuse, dropping a torn final row.

    The incremental checkpoint writer below appends + flushes + fsyncs one row per
    clip, but a crash/power-loss can still land between writes and leave the file's
    LAST row truncated (e.g. a row read back as
    {"clip_row": "2", "transcript": "this is a partial tran"}). csv.DictReader parses
    a truncated row without complaint, so a naive reload would treat a torn row as a
    completed transcript. An intact row always ends in a newline (see the writer), so:
    if the file's last byte is NOT a newline, the final row is torn and is dropped --
    it is simply re-transcribed on resume, which is safe.

    Raises FileNotFoundError if `path` doesn't exist -- callers (main(), below) turn
    that into a clean usage error instead of letting os.path.getsize's raw traceback
    through.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    torn = False
    if os.path.getsize(path):
        with open(path, "rb") as fb:
            fb.seek(-1, os.SEEK_END)
            torn = fb.read(1) != b"\n"
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    dropped = 1 if (torn and rows) else 0
    if dropped:
        rows.pop()
        print(f"asr: sidecar {path}: kept {len(rows)} row(s), dropped {dropped} torn "
              f"final row(s)", file=sys.stderr)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", help="HZDR package dir (required unless --transcripts is "
                    "given; with --transcripts alone, clips missing from it are left "
                    "unbound instead of transcribed)")
    ap.add_argument("--transcripts", help="reuse a transcript sidecar's clip_row/transcript "
                    "columns (skips WhisperX for clips already present there -- a prior "
                    "manifest works too, MANIFEST_COLS is a superset); combine with "
                    "--package to also transcribe whatever's left, resuming a "
                    "crashed/interrupted run")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv")
    ap.add_argument("--wem-metadata", default="out/hzd/wem-metadata.csv")
    ap.add_argument("--catalog", default="out/hzd/catalog.csv")
    ap.add_argument("--out", default="out/hzd/asr-manifest.csv")
    ap.add_argument("--errors", default="out/hzd/asr-manifest-errors.log",
                    help="per-clip decode/archive-read failures: clip_row + reason, "
                         "one per line (see games/hzd/clip_index.py's convention)")
    ap.add_argument("--transcripts-out", default=DEFAULT_TRANSCRIPTS_OUT,
                    help="incremental transcript checkpoint sidecar; appended to per clip "
                         "as it is transcribed so a crash/interrupt loses at most one clip -- "
                         "resume with --transcripts <this file> --package <pkg>")
    ap.add_argument("--sample-cap", type=int, default=300,
                     help="MVP cap on ASR work: transcribe at most this many clips' worth of "
                          "ambiguous buckets (whole buckets, so it may slightly overshoot -- "
                          "see the cap loop below), never the full library, since structural "
                          "binding already resolves most rows without any ASR at all. 0 = "
                          "unlimited (a full pass over every ambiguous bucket -- hours on a "
                          "full library). When a nonzero cap actually truncates work, this "
                          "prints exactly how many ambiguous buckets were left "
                          "untranscribed. Forwarded through `hzd run` (issue #35).")
    ap.add_argument("--all-buckets", action="store_true",
                    help="transcribe every ambiguous bucket, not just story-relevant "
                         "ones (default skips pure ambient/bark collision buckets)")
    a = ap.parse_args(argv)

    cat = load_catalog_dict(a.catalog)
    story_ids = {lid for lid, r in cat.items()
                 if r.get("category") != "ambient" and r.get("subtitle_en", "").strip()}
    lines = [{**m, **{"subtitle_en": cat.get(m["line_id"], {}).get("subtitle_en", "")}}
             for m in _load_csv(a.wem_metadata)]
    clips = _load_csv(a.clip_index)
    buckets = build_buckets(lines, clips)

    rows = []
    # Structural binds are appended sparse here; offset/speaker/subtitle/scene are
    # enriched from catalog metadata at write time (two-pass pattern below).
    for line_id, clip_row, tier in structural_binds(buckets):
        rows.append({"clip_row": clip_row, "line_id": line_id, "tier": "S", "score": 100.0})

    by_row = {int(c["clip_row"]): c for c in clips}
    keep = None if a.all_buckets else (lambda lid: lid in story_ids)
    # Story-relevant ambiguous buckets, each resolved as a WHOLE (assign_bucket needs all of
    # a bucket's clips together to do unique assignment + elimination).
    relevant = relevant_buckets(buckets, keep_line=keep)
    # Cap at BUCKET granularity, never mid-bucket: assign_bucket resolves a bucket as a whole,
    # so a cap that split a bucket would starve it of clips and (formerly) fabricate binds by
    # exclusion. Include whole buckets until the cap is reached (may slightly overshoot).
    want = []
    n_bucket_consumed = 0
    for grp in relevant:
        if a.sample_cap and len(want) >= a.sample_cap:
            break
        want.extend(c["clip_row"] for c in grp["clips"])
        n_bucket_consumed += 1
    want = set(want)
    # Issue #35: a cap that truncates work must never be silent -- every stage that
    # applies it reports success regardless, and (before this) nothing said how much
    # was left on the table. `n_bucket_consumed` stops advancing the moment the cap
    # trips, so every bucket from there to the end of `relevant` was skipped whole.
    n_bucket_skipped = len(relevant) - n_bucket_consumed
    if n_bucket_skipped:
        print(f"asr: SAMPLE CAP APPLIED (--sample-cap={a.sample_cap}): "
              f"{n_bucket_skipped} ambiguous bucket(s) left untranscribed this run -- "
              f"those rows will be absent from the manifest/reels. Re-run with "
              f"--sample-cap 0 (or a higher number) for a full pass.")

    # Transcripts: reuse a prior manifest/sidecar's clip_row+transcript columns (instant
    # re-match, no GPU) and/or run WhisperX for whatever's left. Combining --transcripts
    # with --package resumes a crashed/interrupted run: clips already checkpointed are
    # skipped, only the remainder is (re)transcribed.
    transcripts = {}
    if a.transcripts:
        if not os.path.isfile(a.transcripts):
            ap.error(f"--transcripts path not found: {a.transcripts}")
        for r in _load_transcripts_sidecar(a.transcripts):
            if r["clip_row"] in want:
                transcripts[r["clip_row"]] = r.get("transcript", "")
    n_skipped = len(transcripts)
    remaining = sorted((cr for cr in want if cr not in transcripts), key=int)
    n_transcribed = n_failed = 0

    if remaining:
        if not a.package:
            if not a.transcripts:
                ap.error("--package is required unless --transcripts is given")
            # pure reuse mode (no --package): clips missing from the sidecar simply stay
            # unbound this run -- there's nothing to transcribe them with.
        else:
            from deciwaves.games.hzd.profile import hzd_package_error
            err = hzd_package_error(a.package)
            if err:
                print(err)
                return 1
            dsar = FwPackage(a.package).dsar_for(ARCHIVE)
            model = asr.load_model()
            os.makedirs(os.path.dirname(os.path.abspath(a.transcripts_out)), exist_ok=True)
            os.makedirs(os.path.dirname(os.path.abspath(a.errors)), exist_ok=True)
            sidecar_is_new = not os.path.exists(a.transcripts_out)
            # Heal a torn tail before appending (Task 14c / issue #20 review): a torn
            # final row is dropped in memory by _load_transcripts_sidecar, but the
            # on-disk bytes still end mid-row. If --transcripts-out is the SAME path
            # (the documented resume recipe), appending straight onto that torn tail
            # would merge the next row's bytes into it, producing one corrupt mid-file
            # row no later load can detect. A lone "\n" terminates the torn row as its
            # own (garbled but isolated) row before any new row is appended.
            if not sidecar_is_new and os.path.getsize(a.transcripts_out) > 0:
                with open(a.transcripts_out, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    torn = f.read(1) != b"\n"
                if torn:
                    with open(a.transcripts_out, "a", newline="", encoding="utf-8") as f:
                        f.write("\n")
            # Circuit breaker state (see BREAKER_K docstring): armed until the first
            # success this run; while armed, n_failed IS the count of clips processed
            # so far (all of them failures) since no success has occurred yet.
            breaker_armed = True
            breaker_tripped = False
            with open(a.transcripts_out, "a", newline="", encoding="utf-8") as tf, \
                 open(a.errors, "w", encoding="utf-8") as ferr:
                tw = csv.DictWriter(tf, fieldnames=TRANSCRIPTS_COLS)
                if sidecar_is_new:
                    tw.writeheader()
                for cr in remaining:
                    c = by_row[int(cr)]
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
                        wav = wf.name
                    try:
                        decode_wem_to_wav(dsar.read(int(c["offset"]), int(c["a_bytes"])), wav)
                        text = asr.transcribe(wav, model).text
                    except (Atrac9Error, OSError, wave.Error, ValueError) as exc:
                        # fail-soft: log clip + reason, keep going -- one corrupt clip must
                        # never abort an hours-long GPU run. Not caught: anything NOT a
                        # known decode/archive-read failure (nor KeyboardInterrupt/
                        # SystemExit, which aren't Exception subclasses anyway) still
                        # aborts -- see test_sidecar_checkpoints_incrementally_and_survives_an_abort.
                        ferr.write(f"{cr}\t{type(exc).__name__}: {exc}\n"); ferr.flush()
                        n_failed += 1
                        if breaker_armed and n_failed >= BREAKER_K:
                            breaker_tripped = True
                            break
                        continue
                    finally:
                        os.unlink(wav)
                    transcripts[cr] = text
                    n_transcribed += 1
                    breaker_armed = False   # disarmed for the rest of the run
                    tw.writerow({"clip_row": cr, "transcript": text})
                    tf.flush()
                    os.fsync(tf.fileno())

            if breaker_tripped:
                print(
                    f"asr: ABORT - the first {BREAKER_K} clip(s) processed this run all "
                    f"failed (0 succeeded); this looks like an environment problem "
                    f"(missing/broken decoder or ASR binary, bad model args, etc.), not "
                    f"per-clip corruption. See {a.errors} for details, then try "
                    f"`deciwaves doctor`.",
                    file=sys.stderr,
                )
                return 1

    print(f"asr: transcribed={n_transcribed} skipped={n_skipped} failed={n_failed}")
    if n_failed:
        print(f"asr errors: {n_failed} clip(s) failed, see {a.errors}")
        print(f"resume: rerun with --package {a.package} --transcripts {a.transcripts_out} "
              f"(clips already in {a.transcripts_out} are skipped; failed clips are retried)")

    # Resolve each bucket: unique confident assignment + 1-leftover elimination.
    for grp in relevant:
        crs = [c["clip_row"] for c in grp["clips"] if c["clip_row"] in transcripts]
        if not crs:
            continue
        for cr, (lid, tier, score) in match.assign_bucket(grp["lines"], crs, transcripts).items():
            rows.append({"clip_row": cr, "line_id": lid, "tier": tier,
                         "score": round(score, 1), "transcript": transcripts.get(cr, "")})

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        for r in rows:
            meta = cat.get(r.get("line_id") or "", {})
            w.writerow({**{k: "" for k in MANIFEST_COLS}, **r,
                        "offset": by_row.get(int(r["clip_row"]), {}).get("offset", ""),
                        "speaker_name": meta.get("speaker_name", ""),
                        "subtitle_en": meta.get("subtitle_en", ""),
                        "scene": meta.get("scene", "")})
    bound = [r for r in rows if r.get("line_id")]
    from collections import Counter
    tc = Counter(r["tier"] for r in rows)
    print(f"rows={len(rows)} bound={len(bound)} "
          f"tierS={tc['S']} tier1={tc['1']} tier2={tc['2']} tierE={tc['E']} tier3={tc['3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
