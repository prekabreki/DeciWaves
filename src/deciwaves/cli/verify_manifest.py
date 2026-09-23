"""``deciwaves verify-manifest`` -- deterministic gate for an externally curated manifest.

A curated CSV (rows dropped and/or reordered by an agent or a person) is diffed against the
source CSV it was derived from, before it is rendered verbatim into hours of audio nobody
will read end to end (issue #407). Read-only: it reports and exits, it never writes.

Hard failures (exit code 1), each reported as a count plus up to 5 ``id (row n)`` examples:

- an id in the curated file that the source does not have (invented or corrupted);
- an id that appears more than once in the curated file;
- with ``--path-col``: a referenced audio file that is missing or 0 bytes.

The informational report never affects the exit code: the overall keep rate, the keep rate
per positional bucket of the **source** order (the long-context drift detector -- an editor
that coasted through the middle of the corpus shows as a sagging or spiking bucket; bucketing
the curated order instead would always read ~100%), and with ``--group-col`` the keep rate per
group value. A missing/unreadable/empty file or a missing column is a clean one-line error
with exit code 1, never a traceback.

Game-agnostic: the id and path columns are parameters, so it serves DS (``playlist.csv``,
``line_id``/``stream_path``) and the ``build_spine`` games (``line_id``/``wav``) alike. The id
checks share :func:`deciwaves.engine.catalog_io.classify_ids` with the GUI's order import.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

from deciwaves.engine.catalog_io import classify_ids, format_id_sample

SAMPLE = 5


class _InputError(Exception):
    """A file or column problem that stops the run before any check (exit code 1)."""


def _read(path: str, role: str, required: list[str]) -> list[dict]:
    """The data rows of *path* (``utf-8-sig``: a BOM must not fuse into the first header).
    Raises :class:`_InputError` when the file is missing, unreadable, has no data rows, or
    lacks a *required* column."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            rows = list(reader)
    except FileNotFoundError:
        raise _InputError(f"{role} file not found: {path}") from None
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise _InputError(f"could not read {role} file {path}: {exc}") from None
    if not fields:
        raise _InputError(f"{role} file {path} is empty")
    missing = [c for c in required if c not in fields]
    if missing:
        raise _InputError(f"{role} file {path} has no {', '.join(repr(c) for c in missing)} "
                          f"column (header has: {', '.join(fields)})")
    if not rows:
        raise _InputError(f"{role} file {path} has a header but no rows")
    return rows


def _id(row: dict, col: str) -> str:
    return (row.get(col) or "").strip()


def _pct(kept: int, total: int) -> str:
    return f"{100.0 * kept / total:.1f}%" if total else "n/a"


def _missing_audio(rows: list[dict], path_col: str, root: str) -> list[tuple[str, int]]:
    """``(path, row_number)`` for every curated row whose audio file is absent, not a regular
    file, or 0 bytes. A blank path cell counts as missing."""
    bad = []
    for n, row in enumerate(rows, start=2):
        rel = (row.get(path_col) or "").strip()
        full = os.path.join(root, rel) if rel else ""
        if not rel or not os.path.isfile(full) or os.path.getsize(full) == 0:
            bad.append((rel or "<blank>", n))
    return bad


def _bucket_report(kept_flags: list[bool], buckets: int) -> list[str]:
    """Keep rate per contiguous slice of the SOURCE order. Never more buckets than source
    rows, so a short source can't produce an empty (divide-by-zero) bucket."""
    total = len(kept_flags)
    k = min(buckets, total)
    counts = [[0, 0] for _ in range(k)]  # [kept, rows]
    for i, kept in enumerate(kept_flags):
        b = i * k // total
        counts[b][0] += kept
        counts[b][1] += 1
    lines = [f"keep-rate by source position ({k} bucket(s)):"]
    lines += [f"  bucket {b + 1}/{k}: {_pct(kn, rn)} ({kn}/{rn})" for b, (kn, rn) in enumerate(counts)]
    return lines


def _group_report(source: list[dict], kept_flags: list[bool], group_col: str) -> list[str]:
    """Keep rate per *group_col* value of the source rows, largest source group first."""
    counts: dict[str, list[int]] = {}
    for row, kept in zip(source, kept_flags):
        c = counts.setdefault((row.get(group_col) or "").strip() or "<blank>", [0, 0])
        c[0] += kept
        c[1] += 1
    order = sorted(counts.items(), key=lambda kv: (-kv[1][1], kv[0]))
    lines = [f"keep-rate by {group_col} (source count descending):"]
    lines += [f"  {name}: {_pct(kn, rn)} ({kn}/{rn})" for name, (kn, rn) in order]
    return lines


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deciwaves verify-manifest",
        description="Check a curated manifest CSV against the source CSV it was derived from. "
                    "Exit code 1 on an unknown id, a duplicate id, or (with --path-col) a missing "
                    "or empty audio file; the keep-rate report is informational.")
    ap.add_argument("curated", help="the curated CSV (rows dropped and/or reordered)")
    ap.add_argument("--against", required=True, metavar="SOURCE",
                    help="the source CSV the curated one was derived from")
    ap.add_argument("--id-col", default="line_id", help="id column shared by both files (default: line_id)")
    ap.add_argument("--path-col", default=None,
                    help="curated column holding each row's audio path; enables the missing/empty "
                         "file check (default: skip path checks)")
    ap.add_argument("--path-root", default=".",
                    help="directory --path-col values are relative to (default: the current directory)")
    ap.add_argument("--group-col", default=None,
                    help="source column to report keep rate per value of, e.g. category")
    ap.add_argument("--buckets", type=int, default=10,
                    help="positional buckets of the source order to report keep rate over "
                         "(default: 10; 0 disables)")
    return ap


def run_verify_manifest(argv=None) -> int:
    ap = _build_parser()
    args = ap.parse_args(argv)
    if args.buckets < 0:
        ap.error("--buckets must be 0 or more")
    try:
        source = _read(args.against, "source", [args.id_col] + ([args.group_col] if args.group_col else []))
        curated = _read(args.curated, "curated", [args.id_col] + ([args.path_col] if args.path_col else []))
    except _InputError as exc:
        print(f"verify-manifest: error: {exc}", file=sys.stderr)
        return 1

    source_ids = {_id(r, args.id_col) for r in source} - {""}
    # enumerate from 2: row 1 is the header, so row numbers match the spreadsheet
    ordered = [(_id(r, args.id_col) or "<blank>", n) for n, r in enumerate(curated, start=2)]
    unknown, dupes = classify_ids(ordered, source_ids)
    curated_ids = {lid for lid, _ in ordered}
    kept_flags = [_id(r, args.id_col) in curated_ids for r in source]

    print(f"verify-manifest: {args.curated} against {args.against}")
    print(f"kept {sum(kept_flags)} / {len(source)} source rows ({_pct(sum(kept_flags), len(source))})")
    if args.buckets:
        print("\n".join(_bucket_report(kept_flags, args.buckets)))
    if args.group_col:
        print("\n".join(_group_report(source, kept_flags, args.group_col)))

    failures = []
    if unknown:
        failures.append(f"{len(unknown)} {args.id_col}(s) not in the source: {format_id_sample(unknown, SAMPLE)}")
    if dupes:
        failures.append(f"{len(dupes)} duplicate {args.id_col}(s) (a line can't play twice): "
                        f"{format_id_sample(dupes, SAMPLE)}")
    if args.path_col:
        missing = _missing_audio(curated, args.path_col, args.path_root)
        if missing:
            failures.append(f"{len(missing)} missing or empty audio file(s) in {args.path_col} "
                            f"(under {args.path_root}): {format_id_sample(missing, SAMPLE)}")
    for msg in failures:
        print(f"FAIL: {msg}")
    print(f"verify-manifest: {'FAILED' if failures else 'ok'}")
    return 1 if failures else 0
