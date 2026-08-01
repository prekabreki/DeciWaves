"""FW subtitle/gamescript matcher (story-reel stage).

Re-exports the game-agnostic matcher from engine -- see
``deciwaves.engine.subtitle_match`` for the actual implementation. This module
keeps only the FW-specific ``main()`` CLI (which wires up the FW manifest schema
and FW-local gamescript parser).
"""

from __future__ import annotations

from deciwaves.engine.subtitle_match import build_rows, match_subtitles, split_sentences, StoryBind  # noqa: F401


def main(argv=None):  # pragma: no cover - integration glue
    import argparse
    import csv
    import os
    from collections import Counter

    from deciwaves.games.fw.gamescript import parse_file
    from deciwaves.games.fw.manifest import MANIFEST_COLS
    from deciwaves.games.fw.subtitle_bind import DEFAULT_OUT as _SUBTITLE_MANIFEST

    ap = argparse.ArgumentParser(
        description="FW exact-subtitle -> gamescript story matcher")
    ap.add_argument("--manifest", default=_SUBTITLE_MANIFEST,
                    help="subtitle_bind output (exact in-game subtitles)")
    ap.add_argument("--gamescript", default="docs/forbidden_west_gamescript.md")
    ap.add_argument("--out", default="out/fw/story-manifest.csv")
    ap.add_argument("--strong", type=float, default=90.0)
    ap.add_argument("--accept", type=float, default=80.0)
    ap.add_argument("--min-words", type=int, default=4)
    a = ap.parse_args(argv)

    from deciwaves.engine.catalog_io import read_csv_rows
    manifest = read_csv_rows(a.manifest)
    script_lines = parse_file(a.gamescript)
    binds = match_subtitles(manifest, script_lines, strong=a.strong,
                            accept=a.accept, min_words=a.min_words)
    rows = build_rows(binds)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(rows)
    tc = Counter(r["tier"] for r in rows)
    quests = len({r["quest"] for r in rows})
    print(f"subtitles={len(manifest)} script_lines={len(script_lines)} "
          f"bound={len(rows)} tier1={tc['1']} tier2={tc['2']} "
          f"quests={quests} -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
