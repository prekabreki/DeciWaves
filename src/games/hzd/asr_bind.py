"""MVP orchestration for ASR content-binding (#24): decode -> transcribe -> match -> manifest."""
from __future__ import annotations
import argparse, csv, os, tempfile
from engine.pack.fw_package import FwPackage
from games.hzd import asr, match
from games.hzd.atrac9 import decode_wem_to_wav
from games.hzd.binding import build_buckets, structural_binds

ARCHIVE = "package.01.00.core.stream"
MANIFEST_COLS = ["clip_row", "offset", "line_id", "speaker_name", "subtitle_en", "scene", "tier", "score", "transcript"]


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", help="HZDR package dir (required unless --transcripts)")
    ap.add_argument("--transcripts", help="reuse the transcript column of a prior manifest "
                    "(re-match without re-transcribing); skips WhisperX entirely")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv")
    ap.add_argument("--wem-metadata", default="out/hzd/wem-metadata.csv")
    ap.add_argument("--catalog", default="out/hzd/catalog.csv")
    ap.add_argument("--out", default="out/hzd/asr-manifest.csv")
    ap.add_argument("--sample-cap", type=int, default=300)   # MVP: cap ASR work
    ap.add_argument("--all-buckets", action="store_true",
                    help="transcribe every ambiguous bucket, not just story-relevant "
                         "ones (default skips pure ambient/bark collision buckets)")
    a = ap.parse_args(argv)

    cat = {r["line_id"]: r for r in _load_csv(a.catalog)}
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
    relevant = []
    for grp in buckets.values():
        if not grp["lines"] or (len(grp["lines"]) == 1 and len(grp["clips"]) == 1):
            continue
        if keep is not None and not any(keep(l["line_id"]) for l in grp["lines"]):
            continue
        relevant.append(grp)
    # Cap at BUCKET granularity, never mid-bucket: assign_bucket resolves a bucket as a whole,
    # so a cap that split a bucket would starve it of clips and (formerly) fabricate binds by
    # exclusion (#41). Include whole buckets until the cap is reached (may slightly overshoot).
    want = []
    for grp in relevant:
        if a.sample_cap and len(want) >= a.sample_cap:
            break
        want.extend(c["clip_row"] for c in grp["clips"])
    want = set(want)

    # Transcripts: reuse a prior manifest's column (instant re-match) or run WhisperX.
    transcripts = {}
    if a.transcripts:
        for r in _load_csv(a.transcripts):
            if r["clip_row"] in want:
                transcripts[r["clip_row"]] = r.get("transcript", "")
    else:
        if not a.package:
            ap.error("--package is required unless --transcripts is given")
        dsar = FwPackage(a.package).dsar_for(ARCHIVE)
        model = asr.load_model() if want else None
        for cr in want:
            c = by_row[int(cr)]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                wav = tf.name
            try:
                decode_wem_to_wav(dsar.read(int(c["offset"]), int(c["a_bytes"])), wav)
                transcripts[cr] = asr.transcribe(wav, model).text
            finally:
                os.unlink(wav)

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
