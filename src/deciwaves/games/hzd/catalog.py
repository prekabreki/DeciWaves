"""HZD identification catalog: build out/hzd/catalog.csv from HZD sentence cores.

HZD differs from the DS catalog (games.ds.catalog) in three ways:
* No packfile file-list -- sentence-core paths are harvested by content-scanning the
  pack (games.hzd.inventory), since HZDR exposes only path-hashes.
* Lines are parsed by the self-contained games.hzd.sentence_fw (no pydecima).
* Speaker codes are already human-readable (localized/voices/<name>), so the
  display name is derived from the code rather than followed through simpletext.

Each run also writes ``--cores-out`` (default ``out/hzd/catalog-cores.txt``): the
resolved, dialogue-only core-path list (via ``engine.catalog_io.write_core_paths_sidecar``).
``games.hzd.wem_metadata`` loads it back (``--cores``) instead of repeating this same
full-pack content scan (issue #31).

Invoke as a module (src/ must be on PYTHONPATH)::

    PYTHONPATH=src python -m deciwaves.games.hzd.catalog --package <...\\LocalCacheDX12\\package>
"""
from __future__ import annotations
import argparse
import csv
import os
import sys

from deciwaves.engine.catalog_io import (
    CSV_COLUMNS, processed_core_paths, prune_incomplete_rows, write_core_paths_sidecar,
)
from deciwaves.games.hzd.sentence_fw import parse_sentences_fw
from deciwaves.games.hzd.profile import (
    HZD_ANCHORED_PREFIXES, HZD_FAMILY_PREFIXES, cores_sidecar_header,
)

_SENTENCES_PREFIX = "localized/sentences/"
_SENTENCES_SUFFIX = "/sentences"


def select_sentence_cores(harvested_paths) -> list[str]:
    """Dialogue sentence cores only (drop voice ``/simpletext`` cores), sorted."""
    return sorted(p for p in harvested_paths if p.endswith(_SENTENCES_SUFFIX))


def classify_hzd(core_path: str, family_prefixes: dict | None = None) -> tuple[str, str]:
    """Return ``(category, scene)`` for an HZD sentence-core virtual path.

    ``scene`` is the path between ``localized/sentences/`` and ``/sentences``.
    ``category`` is a quest-family heuristic keyed on the first scene segment
    (``mq*``->main_quest, ``sq*``->side_quest, ``dlc*``->dlc, ...), else ``other``.
    """
    if family_prefixes is None:
        family_prefixes = HZD_FAMILY_PREFIXES
    scene = core_path
    if scene.startswith(_SENTENCES_PREFIX):
        scene = scene[len(_SENTENCES_PREFIX):]
    if scene.endswith(_SENTENCES_SUFFIX):
        scene = scene[: -len(_SENTENCES_SUFFIX)]
    first = scene.split("/", 1)[0]
    category = "other"
    # longest-prefix match so "collectab" wins over a hypothetical "co"
    for pref in sorted(family_prefixes, key=len, reverse=True):
        if not first.startswith(pref):
            continue
        # Short quest codes (mq/sq/ec/dlc) must anchor on a word boundary: the char after
        # the code must not be a letter, else "eclipse"/"square"/"mqueen" get swallowed.
        # Word-stem prefixes (collectab/aigenerated/shops) keep plain substring matching.
        if pref in HZD_ANCHORED_PREFIXES:
            rest = first[len(pref):]
            if rest and rest[0].isalpha():
                continue
        category = family_prefixes[pref]
        break
    return category, scene


def speaker_name_from_code(speaker_code: str) -> str:
    """Derive a display name from a readable HZD voice path (e.g.
    ``localized/voices/aloy_child`` -> ``aloy_child``). HZD codes are already
    legible, so no simpletext follow is needed for a usable name."""
    return speaker_code.rsplit("/", 1)[-1] if speaker_code else ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True,
                    help=r"HZDR LocalCacheDX12\package directory")
    ap.add_argument("--out", default="out/hzd/catalog.csv")
    ap.add_argument("--errors", default="out/hzd/catalog-errors.log")
    ap.add_argument("--processed", default="out/hzd/catalog-processed.txt")
    ap.add_argument("--cores-out", default="out/hzd/catalog-cores.txt",
                    help="sidecar of this run's dialogue sentence-core paths (post "
                         "select_sentence_cores filtering); wem-metadata reads this "
                         "back (--cores) instead of repeating the content scan below")
    ap.add_argument("--sample-cap", type=int, default=0,
                    help="0 = scan the whole pack; >0 caps records scanned during harvest "
                         "(smoke test). A capped run leaves --cores-out untouched, since a "
                         "truncated core list would poison the sidecar wem-metadata trusts.")
    args = ap.parse_args(argv)

    from deciwaves.games.hzd.profile import build_profile, hzd_package_error
    from deciwaves.games.hzd.inventory import harvest_sentence_cores
    err = hzd_package_error(args.package)
    if err:
        print(err)
        return 1
    profile = build_profile(args.package)
    fw = profile.pack_reader

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    print("harvesting sentence-core paths (content scan)...", flush=True)
    harvested = harvest_sentence_cores(fw, sample_cap=args.sample_cap or None)
    paths = select_sentence_cores(harvested)
    # Persist this run's resolved dialogue-core list so wem-metadata (--cores) can
    # reuse it instead of repeating this same full-pack scan (issue #31) -- BUT NOT
    # when the harvest was capped (finding 6): a --sample-cap'd smoke-test run yields
    # a TRUNCATED core list, and wem-metadata trusts the sidecar (ignoring its own
    # --sample-cap when one exists), so overwriting the shared sidecar with the capped
    # subset would silently shrink wem-metadata.csv. Leave any existing full sidecar
    # standing and say so.
    if args.sample_cap > 0:
        print(f"sample-cap active: catalog-cores sidecar left untouched ({args.cores_out})")
    else:
        # Header = a locators-file fingerprint (issue #45): lets wem_metadata detect a
        # sidecar harvested from a since-patched pack instead of trusting it forever.
        write_core_paths_sidecar(args.cores_out, paths, header=cores_sidecar_header(args.package))
    # The processed sidecar is the SOLE resume authority (issue #21): a core's sidecar
    # line is only written after all of its rows are in the CSV, so a mid-core crash
    # can leave partial CSV rows for a core the sidecar never confirmed. Drop those
    # before computing "done", or a partial core would be silently treated as finished.
    dropped = prune_incomplete_rows(args.out, args.processed)
    if dropped:
        print(f"resume: dropped {dropped} row(s) left by an incomplete previous run "
              f"(core(s) not confirmed done in {args.processed})")
    done = processed_core_paths(args.processed)
    todo = [p for p in paths if p not in done]
    print(f"{len(paths)} dialogue cores; {len(done)} done; {len(todo)} to do")

    # exists AND non-empty -- a 0-byte file left by a crash right after creating
    # (but before writing) the CSV must still get a header, else the first data
    # row silently becomes the fieldnames on the next load (fcc0d1c, finding 9).
    new_file = not os.path.isfile(args.out) or os.path.getsize(args.out) == 0
    cores_ok = cores_failed = total_lines = 0
    with open(args.out, "a", newline="", encoding="utf-8") as fout, \
         open(args.errors, "a", encoding="utf-8") as ferr, \
         open(args.processed, "a", encoding="utf-8") as fproc:
        writer = csv.DictWriter(fout, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        for core_path in todo:
            cat, scene = classify_hzd(core_path)
            line_errs = []
            try:
                core_bytes = fw.read_core(core_path)
                rows = parse_sentences_fw(
                    core_bytes, on_line_error=lambda i, e: line_errs.append((i, e)))
            except Exception as exc:  # fail-soft per core
                cores_failed += 1
                ferr.write(f"{core_path}\t{type(exc).__name__}: {exc}\n"); ferr.flush()
                fproc.write(core_path + "\n"); fproc.flush()
                continue
            for ln in rows:
                writer.writerow({
                    "line_id": ln.line_id, "core_path": core_path,
                    "line_index": ln.line_index, "category": cat, "scene": scene,
                    "speaker_code": ln.speaker_code,
                    "speaker_name": speaker_name_from_code(ln.speaker_code),
                    "subtitle_en": ln.subtitle_en, "wem_path_en": ln.wem_path_en,
                    "language": "english"})
            for i, e in line_errs:
                ferr.write(f"{core_path}#{i}\t{type(e).__name__}: {e}\n")
            fout.flush(); ferr.flush()
            fproc.write(core_path + "\n"); fproc.flush()
            cores_ok += 1
            total_lines += len(rows)
    print(f"done: {cores_ok} cores, {cores_failed} failed, {total_lines} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
