"""Emit per-line (A,B) media metadata and report story-line coverage (the ASR-gate check)."""
from __future__ import annotations
import argparse
import csv
import os

from deciwaves.games.hzd.profile import build_profile
from deciwaves.games.hzd.inventory import harvest_sentence_cores
from deciwaves.games.hzd.sentence_fw import parse_sentence_media

COLUMNS = ["line_id", "a_bytes", "b_samples"]


def coverage_report(metadata_csv: str, catalog_csv: str) -> dict:
    """Return coverage stats for story-usable catalog lines.

    A catalog row is "story" iff ``category != "ambient"`` AND
    ``subtitle_en.strip()`` is non-empty.  Returns a dict with keys
    ``story_lines``, ``with_ab``, and ``coverage_pct``.
    """
    def _pos_int(s: str) -> int:
        try:
            return int(s.strip())
        except (ValueError, AttributeError):
            return 0

    with open(metadata_csv, newline="", encoding="utf-8") as f:
        have = {
            r["line_id"]
            for r in csv.DictReader(f)
            if _pos_int(r.get("a_bytes", "")) > 0 and _pos_int(r.get("b_samples", "")) > 0
        }
    story, with_ab = 0, 0
    with open(catalog_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            # Defensive .get (mirrors the metadata-side reads above): an older/partial/
            # hand-edited catalog missing these columns degrades to "not story" rather
            # than crashing the ASR acceptance gate with a KeyError.
            if r.get("category") == "ambient" or not (r.get("subtitle_en") or "").strip():
                continue
            story += 1
            if r["line_id"] in have:
                with_ab += 1
    pct = round(100.0 * with_ab / story, 1) if story else 0.0
    return {"story_lines": story, "with_ab": with_ab, "coverage_pct": pct}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Emit wem-metadata.csv and report story-line (A,B) coverage.")
    ap.add_argument("--package", required=True,
                    help=r"HZDR LocalCacheDX12\package directory")
    ap.add_argument("--out", default="out/hzd/wem-metadata.csv")
    ap.add_argument("--catalog", default="out/hzd/catalog.csv")
    ap.add_argument("--sample-cap", type=int, default=0,
                    help="0 = scan the whole pack; >0 caps records scanned during harvest")
    a = ap.parse_args(argv)

    profile = build_profile(a.package)
    fw = profile.pack_reader

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    # harvest_sentence_cores returns list[str] paths; read bytes via fw.read_core.
    # Mirror catalog.py: convert 0 -> None so harvest scans the full pack.
    paths = harvest_sentence_cores(fw, sample_cap=a.sample_cap or None)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for core_path in paths:
            try:
                core_bytes = fw.read_core(core_path)
            except Exception:
                continue
            for m in parse_sentence_media(core_bytes, on_line_error=lambda *_: None):
                w.writerow([m.line_id, m.a_bytes, m.b_samples])

    print(coverage_report(a.out, a.catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
