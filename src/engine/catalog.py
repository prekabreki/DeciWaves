"""Phase B: build out/catalog.csv from all story-dialogue sentences cores.

Invoke as a module (package form):
    python -m engine.catalog --data-dir <DS:DC/data> --oodle <oo2core_7_win64.dll>
"""
from __future__ import annotations
import argparse
import csv
import os
import sys

import pydecima.reader as _pydecima_reader
from engine.sentence_core import parse_sentences
from engine.speakers import SpeakerMap

# Alias for backward compatibility (imported by some tests and callers).
# Authoritative map is games.ds.profile.DS_CORE_PREFIXES — catalog merely aliases it.
from games.ds.profile import DS_CORE_PREFIXES as CORE_PREFIXES  # noqa: E402

CSV_COLUMNS = ["line_id", "core_path", "line_index", "category", "scene",
               "speaker_code", "speaker_name", "subtitle_en", "wem_path_en", "language"]


def select_core_paths(file_list_lines, core_prefixes=None):
    """Return the sentence core virtual paths that match *core_prefixes*.

    Parameters
    ----------
    file_list_lines:
        Iterable of raw lines from the packfile file-list.
    core_prefixes:
        Mapping ``{prefix: category}`` controlling which paths are selected.
        Defaults to the module-level ``CORE_PREFIXES`` for backward compatibility.
    """
    if core_prefixes is None:
        core_prefixes = CORE_PREFIXES
    out = []
    for raw in file_list_lines:
        p = raw.strip()
        if not p.endswith("/sentences"):
            continue
        if any(p.startswith(pref + "/") for pref in core_prefixes):
            out.append(p)
    return out


def classify(core_path, core_prefixes=None):
    """Return ``(category, scene)`` for *core_path* using *core_prefixes*.

    Parameters
    ----------
    core_path:
        Virtual path of a sentence ``.core`` (without extension).
    core_prefixes:
        Mapping ``{prefix: category}``.  Defaults to the module-level
        ``CORE_PREFIXES`` for backward compatibility.
    """
    if core_prefixes is None:
        core_prefixes = CORE_PREFIXES
    for pref, cat in core_prefixes.items():
        if core_path.startswith(pref + "/"):
            scene = core_path[len(pref) + 1:].rsplit("/sentences", 1)[0]
            return cat, scene
    return "unknown", ""


def done_core_paths(csv_path):
    if not os.path.isfile(csv_path):
        return set()
    done = set()
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add(row["core_path"])
    return done


def processed_core_paths(processed_path):
    """Cores that reached a terminal outcome (rows, zero-rows, OR hard-failure). Unlike the CSV,
    this also records cores that parsed to zero rows or failed -- which leave no CSV row and
    would otherwise silently re-run every invocation (issue #3)."""
    if not os.path.isfile(processed_path):
        return set()
    with open(processed_path, "r", encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--file-list", default="out/data-file-list.txt")
    ap.add_argument("--out", default="out/catalog.csv")
    ap.add_argument("--errors", default="out/catalog-errors.log")
    ap.add_argument("--processed", default="out/catalog-processed.txt")
    args = ap.parse_args(argv)

    from games.ds.profile import build_profile
    profile = build_profile(args.data_dir, args.oodle)

    _pydecima_reader.set_globals(_decima_version=profile.decima_version)

    file_list_lines = open(args.file_list, encoding="utf-8").read().splitlines()
    paths = select_core_paths(file_list_lines, profile.core_prefixes)
    # Resume = union of (cores that produced CSV rows) and (cores recorded as processed).
    # The sidecar covers zero-row and hard-failed cores that the CSV cannot represent.
    done = done_core_paths(args.out) | processed_core_paths(args.processed)
    todo = [p for p in paths if p not in done]
    print(f"{len(paths)} dialogue cores; {len(done)} done; {len(todo)} to do")

    idx = profile.pack_reader
    speakers_cache = os.path.join(os.path.dirname(args.out), "speakers.json")
    smap = SpeakerMap(idx, file_list_lines, cache_path=speakers_cache,
                      simpletext_filter=profile.speaker_simpletext_filter)
    print(f"speaker map: {len(smap)} voices loaded")
    new_file = not os.path.isfile(args.out)
    cores_ok = cores_failed = total_lines = 0
    with open(args.out, "a", newline="", encoding="utf-8") as fout, \
         open(args.errors, "a", encoding="utf-8") as ferr, \
         open(args.processed, "a", encoding="utf-8") as fproc:
        writer = csv.DictWriter(fout, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        for core_path in todo:
            cat, scene = classify(core_path, profile.core_prefixes)
            line_errs = []
            try:
                core_bytes = idx.read_core(core_path)
                rows = parse_sentences(
                    core_bytes,
                    on_line_error=lambda i, e: line_errs.append((i, e)))
            except Exception as exc:
                cores_failed += 1
                ferr.write(f"{core_path}\t{type(exc).__name__}: {exc}\n")
                ferr.flush()
                fproc.write(core_path + "\n"); fproc.flush()  # terminal: hard-failure
                continue
            for ln in rows:
                writer.writerow({
                    "line_id": ln.line_id, "core_path": core_path,
                    "line_index": ln.line_index, "category": cat, "scene": scene,
                    "speaker_code": ln.speaker_code,
                    "speaker_name": smap.name_for(ln.speaker_code),
                    "subtitle_en": ln.subtitle_en, "wem_path_en": ln.wem_path_en,
                    "language": "english"})
            for i, e in line_errs:
                ferr.write(f"{core_path}#{i}\t{type(e).__name__}: {e}\n")
            fout.flush(); ferr.flush()
            fproc.write(core_path + "\n"); fproc.flush()  # terminal: parsed (rows or zero-rows)
            cores_ok += 1
            total_lines += len(rows)
    print(f"done: {cores_ok} cores, {cores_failed} failed, {total_lines} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
