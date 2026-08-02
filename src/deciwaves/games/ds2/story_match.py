"""DS2 ASR-transcript -> gamescript story matcher.

DS2 has no exact subtitles (the object reader is blocked), so it matches the
gamescript against ASR transcripts instead. Each clip's transcript is also its
stand-in "subtitle" for the matcher.

Joins clip-index + transcripts on `line_id` (inner join -- a failed ASR clip is
absent by design), then calls the game-agnostic fuzzy matcher from engine.
"""

from __future__ import annotations


def main(argv=None) -> int:  # pragma: no cover - integration glue
    import argparse
    import csv
    import os
    from collections import Counter

    from deciwaves.engine.catalog_io import read_csv_rows
    from deciwaves.engine.gamescript import parse_file
    from deciwaves.engine.subtitle_match import (
        ELLIPSIS_TERMINATORS, build_rows, match_subtitles,
    )

    MANIFEST_COLS = ["line_id", "wav", "speaker", "subtitle", "gamescript_index",
                     "quest", "tier", "score", "transcript"]

    ap = argparse.ArgumentParser(
        description="DS2 ASR-transcript -> gamescript story matcher")
    ap.add_argument("--clip-index", default="out/ds2/clip-index.csv")
    ap.add_argument("--transcripts", default="out/ds2/transcripts.csv")
    ap.add_argument("--gamescript", required=True,
                    help="path to your own Death Stranding 2 gamescript (BYO)")
    ap.add_argument("--out", default="out/ds2/story-manifest.csv")
    ap.add_argument("--strong", type=float, default=90.0)
    ap.add_argument("--accept", type=float, default=80.0)
    ap.add_argument("--min-words", type=int, default=4)
    a = ap.parse_args(argv)

    clips = read_csv_rows(a.clip_index, required=["line_id", "wav"])
    txs = read_csv_rows(a.transcripts, required=["line_id", "transcript"])
    tx_map = {r["line_id"]: r["transcript"] for r in txs}

    # inner join: only clips that have a transcript
    manifest = [{"line_id": r["line_id"], "wav": r["wav"],
                  "subtitle": tx_map[r["line_id"]],
                  "transcript": tx_map[r["line_id"]]}
                for r in clips if r["line_id"] in tx_map]

    script_lines = parse_file(a.gamescript)
    # DS2's gamescript ends sentences with `…` as well as `.!?` (issue #393).
    binds = match_subtitles(manifest, script_lines, strong=a.strong,
                            accept=a.accept, min_words=a.min_words,
                            terminators=ELLIPSIS_TERMINATORS)
    rows = build_rows(binds)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    tc = Counter(r["tier"] for r in rows)
    quests = len({r["quest"] for r in rows})
    print(f"clips={len(clips)} transcripts={len(txs)} joined={len(manifest)} "
          f"script_lines={len(script_lines)} "
          f"bound={len(rows)} tier1={tc['1']} tier2={tc['2']} "
          f"quests={quests} -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
