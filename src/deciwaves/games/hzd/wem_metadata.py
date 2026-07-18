"""Emit per-line (A,B) media metadata and report story-line coverage (the ASR-gate check).

Core-path resolution (issue #31): by default this stage loads the dialogue-only
core-path list the `hzd catalog` stage already harvested and persisted to a sidecar
(``--cores``, via ``engine.catalog_io.write_core_paths_sidecar`` /
``read_core_paths_sidecar``), instead of repeating catalog's full-pack content scan.
If that sidecar is missing (e.g. this stage is run standalone, without a prior
`hzd catalog`), it falls back to rescanning the pack itself via
``inventory.harvest_sentence_cores`` + ``catalog.select_sentence_cores`` -- the same
filter catalog applies -- so `/simpletext` cores (which cannot contain sentences) are
never handed to the sentence-media parser either way.

Staleness detection against the live pack (issue #45): the sidecar carries a
``games.hzd.profile.cores_sidecar_header`` comment line -- a ``PackFileLocators.bin``
size:mtime_ns fingerprint stamped by `hzd catalog` at write time. On load:
* Header present and matching the live pack -> trusted silently (as before).
* Header present but MISMATCHED (a patch since rewrote the locator index) -> a loud
  one-line warning naming the sidecar, the sidecar is ignored, and the pack is
  re-harvested from scratch -- overwriting the sidecar with a fresh header (unless
  ``--sample-cap`` truncated this run's harvest, in which case the shared sidecar is
  left untouched rather than poisoned with a partial list, mirroring `hzd catalog`'s
  own sample-cap guard).
* No header at all (a sidecar written before issue #45) -> staleness can't be checked;
  warn once and TRUST it as-is, so no pre-existing workspace is forced to regenerate.

Per-core and per-line parse failures are recorded to ``--errors`` (mirroring
`hzd catalog`'s own errors file) rather than silently dropped -- this is the same
stage family whose old `ff 0f` marker silently lost ~1,109 story lines (see
sentence_fw.py's history comment), so swallowing errors here is exactly backwards.
"""
from __future__ import annotations
import argparse
import csv
import os

from deciwaves.engine.catalog_io import (
    read_core_paths_sidecar, read_core_paths_sidecar_header, write_core_paths_sidecar,
)
from deciwaves.engine.coverage import (
    clear_stage_coverage, default_coverage_path, write_stage_coverage,
)
from deciwaves.games.hzd.profile import build_profile, cores_sidecar_header
from deciwaves.games.hzd.inventory import harvest_sentence_cores, write_harvest_read_errors
from deciwaves.games.hzd.catalog import select_sentence_cores
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
    ap.add_argument("--cores", default="out/hzd/catalog-cores.txt",
                    help="core-path sidecar written by `hzd catalog` (--cores-out); "
                         "reused here to skip re-harvesting. If absent, falls back to "
                         "rescanning the pack (--sample-cap applies to that fallback only)")
    ap.add_argument("--errors", default="out/hzd/wem-metadata-errors.log")
    ap.add_argument("--coverage-out", default=default_coverage_path("hzd"),
                    help="per-game coverage summary JSON this stage merges its "
                         "story-coverage section into (issue #63) -- the same "
                         "numbers as the stdout report, persisted")
    ap.add_argument("--sample-cap", type=int, default=0,
                    help="0 = scan the whole pack; >0 caps records scanned during a "
                         "rescan (the missing-sidecar fallback, or a stale-sidecar "
                         "regeneration -- ignored when --cores sidecar is found AND "
                         "trusted)")
    a = ap.parse_args(argv)

    # Invalidate this stage's prior coverage section on ENTRY -- before any
    # early-return failure path below -- so a forced re-run (marker deleted)
    # that fails the preflight, or can't recompute coverage, leaves "coverage
    # unknown" rather than a stale claim, keeping section-absent == marker-absent
    # in sync (issue #81; #87 finding 2). Only a successful run re-writes the
    # section at the end.
    clear_stage_coverage(a.coverage_out, "wem-metadata")

    from deciwaves.games.hzd.profile import hzd_package_error
    err = hzd_package_error(a.package)
    if err:
        print(err)
        return 1

    profile = build_profile(a.package)
    fw = profile.pack_reader

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)

    # Staleness check (issue #45): a header-carrying sidecar is compared against the
    # live pack's locators fingerprint; see the module docstring for the 3 outcomes.
    paths = read_core_paths_sidecar(a.cores)
    stale = False
    rescanned = False   # did the pack get (re)scanned this run? -> whether --sample-cap applied
    if paths is not None:
        header = read_core_paths_sidecar_header(a.cores)
        if header is None:
            print(f"WARNING: {a.cores} has no locators fingerprint header (written "
                  f"before issue #45) -- staleness can't be checked against the live "
                  f"pack; trusting it as-is. Re-run `hzd catalog` to add one.")
        else:
            expected = cores_sidecar_header(a.package)
            if header != expected:
                print(f"WARNING: {a.cores} is STALE (locators fingerprint changed -- "
                      f"sidecar has {header!r}, pack now has {expected!r}, likely a "
                      f"game patch) -- ignoring it and re-harvesting the pack from "
                      f"scratch.")
                paths = None
                stale = True

    harvest_read_errors: list[tuple[int, Exception]] = []
    if paths is None:
        if not stale:
            print(f"wem-metadata: no core-path sidecar at {a.cores} -- rescanning the pack "
                  f"(run `hzd catalog` first to skip this full-pack scan)", flush=True)
        # The fallback rescan reaches the same harvest content-scan catalog does, so it
        # inherits the same silent-drop hazard (issue #66 / spec §5.4): record read
        # failures instead of losing them.
        harvested = harvest_sentence_cores(
            fw, sample_cap=a.sample_cap or None,
            on_read_error=lambda h, exc: harvest_read_errors.append((h, exc)))
        paths = select_sentence_cores(harvested)
        rescanned = True
        if stale:
            if a.sample_cap:
                print(f"sample-cap active: stale {a.cores} left untouched, not "
                      f"overwritten with this run's capped/truncated re-harvest "
                      f"(re-run with --sample-cap 0 to refresh it)")
            else:
                write_core_paths_sidecar(a.cores, paths, header=cores_sidecar_header(a.package))
                print(f"wem-metadata: refreshed {a.cores} with {len(paths)} core(s)")

    cores_failed = 0
    lines_written = 0
    with open(a.out, "w", newline="", encoding="utf-8") as f, \
         open(a.errors, "w", encoding="utf-8") as ferr:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        # Harvest-scan read failures (issue #66), via the shared inventory writer so
        # this log and catalog's stay byte-identical for the GUI issues panel (spec
        # §5.4). This log is opened "w" (truncated each run), so no dedup (skip_tags) is
        # needed -- unlike catalog's append-mode log. Empty unless this run took the
        # fallback rescan path (a trusted sidecar skips the harvest entirely).
        write_harvest_read_errors(ferr, harvest_read_errors)
        ferr.flush()
        for core_path in paths:
            line_errs = []
            try:
                core_bytes = fw.read_core(core_path)
                media = parse_sentence_media(
                    core_bytes, on_line_error=lambda i, e: line_errs.append((i, e)),
                    core_path=core_path)
            except Exception as exc:  # fail-soft per core, like catalog.py
                cores_failed += 1
                ferr.write(f"{core_path}\t{type(exc).__name__}: {exc}\n"); ferr.flush()
                continue
            for m in media:
                w.writerow([m.line_id, m.a_bytes, m.b_samples])
                lines_written += 1
            for i, e in line_errs:
                ferr.write(f"{core_path}#{i}\t{type(e).__name__}: {e}\n")
            ferr.flush()

    print(f"wem-metadata: {len(paths)} cores ({cores_failed} failed), "
          f"{lines_written} lines, {len(harvest_read_errors)} unreadable during harvest "
          f"-> {a.out}")
    # Coverage bookkeeping must never fail a stage whose real product -- the
    # metadata CSV above, built WITHOUT the catalog -- already succeeded (issue
    # #87 finding 1). coverage_report opens --catalog, which a missing or
    # UTF-16-resaved file makes raise (FileNotFoundError/UnicodeDecodeError)
    # AFTER the CSV is written; under `hzd run` that would discard a completed
    # stage. On failure: warn and exit 0, leaving the section absent (cleared on
    # entry) = "coverage unknown", since it couldn't be computed.
    try:
        report = coverage_report(a.out, a.catalog)
        print(report)
        # Persist what the report prints (issue #63): coverage numbers were
        # stdout-only, so a partial scan looked complete on disk.
        write_stage_coverage(a.coverage_out, "wem-metadata", {
            "cores": len(paths), "cores_failed": cores_failed,
            "lines_written": lines_written,
            # The cap in effect (issue #81, #87 finding 5): recorded only when a
            # rescan actually ran -- a trusted sidecar makes --sample-cap a
            # no-op, and a complete scan must not read as capped on disk.
            "sample_cap": a.sample_cap if rescanned else 0, **report})
    except (OSError, ValueError) as exc:
        print(f"warning: couldn't compute story coverage from {a.catalog} "
              f"({exc}) -- the metadata CSV {a.out} is unaffected; this stage's "
              f"coverage is left unknown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
