"""Recover the HZD line->stream binding from a running-game memory dump.

Strategy A of docs/runtime-binding-plan.md. The disk hunt proved the resource GUID
and its stream key are NOT co-located on disk, but at runtime the engine MUST build
that association in RAM to play the right audio. This scans a full-process dump for
any resident binding record: a known stream key (from PackFileLocators.bin) sitting
near a known resource GUID / sentence uuid (from line_ids.csv).

The scan is two-sided and data-driven (NOT oracle-only):

1. Valid stream-key set = every ``hash`` of a ``package.01.00.core.stream`` locator
   entry (~67k u64). These are the only 64-bit values that can be a real stream key.
2. GUID/uuid set = the 16-byte sound_resource_guid + sentence_uuid of every line
   (from line_ids.csv), each mapped back to its line_id.

Fast path: mmap the dump, reinterpret as ``<u8`` (8-byte-aligned), and use
``np.isin`` to find every offset holding a valid key. Records in RAM are ~certainly
8-byte aligned, so the keys land on aligned slots; we also offer a 4-byte-aligned
pass. For each key hit we look +/-window bytes for any GUID/uuid in the set (few, so
cheap). A delta (guid_off - key_off) repeated across many hits == the record stride.
If a dominant delta exists, SWEEP every key hit at that delta -> the recovered
line -> key binding for everything resident in the dump.

Usage::

    python tools/hzd_memscan.py --dump game.dmp --ids out/hzd/line_ids.csv \\
        [--package <pkg dir>] [--archive package.01.00.core.stream] \\
        [--table out/hzd/bindings.csv] [--window 512]

Exit codes:
    0  bindings recovered (a consistent delta was found and swept)
    1  GUIDs/uuids resident but NO consistent key->guid delta (pointer-linked
       record -> pivot to the Frida hook, Strategy B)
    2  no relevant data resident (no key hit OR no guid hit -> dump too early /
       wrong scene; reach a dialogue scene and dump again)
"""
from __future__ import annotations
import argparse
import csv
import mmap
import os
import struct
import sys
from collections import Counter
from dataclasses import dataclass

# --- oracle constants (see docs/runtime-binding-plan.md), kept for reference/tests ---
ORACLE_GUID_HEX = "13f9532a11e94b6fbe26665e27bf4c3e"  # raw 16-byte on-disk order
ORACLE_KEY = 0x3E0F9D4305030200                       # u64 stream key
ORACLE_OFFSET = 0x07EEA882                             # logical offset in pkg01 stream
ORACLE_LENGTH = 0x00146E24                             # decoded clip byte length

DEFAULT_PACKAGE = (
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"
)
DEFAULT_ARCHIVE = "package.01.00.core.stream"
DEFAULT_IDS = "out/hzd/line_ids.csv"
DEFAULT_CATALOG = "out/hzd/catalog.csv"

EXIT_RECOVERED = 0
EXIT_NO_DELTA = 1
EXIT_NOT_RESIDENT = 2


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def load_key_set(package_dir: str, archive: str) -> dict[int, tuple[int, int]]:
    """Map stream key (u64) -> (offset, length) for every locator entry in
    `archive`. The `hash` of a .core.stream entry IS the stream key."""
    from deciwaves.engine.pack.hzd_locators import HzdLocators
    loc = HzdLocators(os.path.join(package_dir, "PackFileLocators.bin"))
    return {e.hash: (e.offset, e.length) for e in loc.entries(archive)}


@dataclass(frozen=True)
class IdEntry:
    line_id: str
    kind: str   # "guid" or "uuid"


def load_id_set(ids_csv: str) -> dict[bytes, IdEntry]:
    """Map each 16-byte GUID/uuid -> (line_id, kind) from line_ids.csv.

    Both sound_resource_guid and sentence_uuid are indexed; either appearing near
    a key in RAM identifies the line.
    """
    out: dict[bytes, IdEntry] = {}
    with open(ids_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lid = row["line_id"]
            g = row.get("sound_resource_guid", "")
            u = row.get("sentence_uuid", "")
            if len(g) == 32:
                out.setdefault(bytes.fromhex(g), IdEntry(lid, "guid"))
            if len(u) == 32:
                out.setdefault(bytes.fromhex(u), IdEntry(lid, "uuid"))
    return out


def load_catalog(catalog_csv: str) -> dict[str, dict]:
    """line_id -> catalog row (speaker_name, subtitle_en, ...), if available."""
    if not catalog_csv or not os.path.isfile(catalog_csv):
        return {}
    out: dict[str, dict] = {}
    with open(catalog_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["line_id"], row)
    return out


# --------------------------------------------------------------------------- #
# Pure scan core (unit-tested)
# --------------------------------------------------------------------------- #
def find_key_offsets(buf, key_set, stride: int = 8) -> dict[int, int]:
    """Byte offsets in `buf` whose `stride`-aligned u64 is in `key_set`.

    Returns {byte_offset: key}. Uses numpy when available (fast, vectorised over
    multi-GB dumps); falls back to a struct-based stride loop otherwise.
    """
    if not key_set:
        return {}
    try:
        import numpy as np
    except ImportError:
        return _find_key_offsets_py(buf, key_set, stride)

    if stride != 8:
        # callers union the other alignment classes via find_key_offsets_aligned.
        raise ValueError("numpy fast path supports stride==8; use find_key_offsets_aligned")
    n8 = len(buf) - (len(buf) % 8)
    if n8 == 0:
        return {}
    arr = np.frombuffer(buf, dtype=np.uint8, count=n8)
    vals = arr.view("<u8")
    base = 0
    keys = np.fromiter(key_set, dtype="<u8", count=len(key_set))
    keys.sort()
    idx = np.searchsorted(keys, vals)
    idx_clamped = np.minimum(idx, len(keys) - 1)
    hit_mask = keys[idx_clamped] == vals
    positions = np.nonzero(hit_mask)[0]
    return {int(p) * 8 + base: int(vals[p]) for p in positions}


def _find_key_offsets_py(buf, key_set, stride: int) -> dict[int, int]:
    """Dependency-light fallback: walk stride-aligned u64 slots in pure Python."""
    out: dict[int, int] = {}
    n = len(buf)
    mv = memoryview(buf)
    unpack = struct.Struct("<Q").unpack_from
    for off in range(0, n - 7, stride):
        (v,) = unpack(mv, off)
        if v in key_set:
            out[off] = v
    return out


def find_key_offsets_aligned(buf, key_set, four_byte: bool = True) -> dict[int, int]:
    """Key offsets at 8-byte alignment, plus the 4-byte-shifted class if requested.

    Records in RAM are near-certainly 8-aligned, but a 4-aligned key can still be a
    real record laid out on a 4-byte boundary, so we optionally union the +4 class.
    """
    hits = find_key_offsets(buf, key_set, stride=8)
    if not four_byte:
        return hits
    try:
        import numpy as np
    except ImportError:
        for off, v in _find_key_offsets_py(buf, key_set, stride=4).items():
            hits.setdefault(off, v)
        return hits
    if not key_set or len(buf) < 12:
        return hits
    # view the buffer offset by 4 bytes, then 8-stride over that -> the +4 class.
    tail = len(buf) - 4
    n8 = tail - (tail % 8)
    if n8 == 0:
        return hits
    arr = np.frombuffer(buf, dtype=np.uint8, count=4 + n8)[4:4 + n8]
    vals = arr.view("<u8")
    keys = np.fromiter(key_set, dtype="<u8", count=len(key_set))
    keys.sort()
    idx = np.minimum(np.searchsorted(keys, vals), len(keys) - 1)
    positions = np.nonzero(keys[idx] == vals)[0]
    for p in positions:
        hits.setdefault(int(p) * 8 + 4, int(vals[p]))
    return hits


@dataclass(frozen=True)
class Hit:
    key_off: int
    key: int
    id_off: int
    id_bytes: bytes
    line_id: str
    kind: str
    delta: int   # id_off - key_off


def collect_hits(buf, key_offsets: dict[int, int], id_set: dict[bytes, IdEntry],
                 window: int) -> list[Hit]:
    """For every key offset, scan +/-window for any 16-byte slice in `id_set`.

    The id_set is tiny per-window relative to the dump, so a per-byte slice check
    inside each window is cheap (window<=~1KB, few key hits).
    """
    out: list[Hit] = []
    n = len(buf)
    mv = memoryview(buf)
    for koff, key in key_offsets.items():
        lo = max(0, koff - window)
        hi = min(n - 16, koff + window)
        for off in range(lo, hi + 1):
            chunk = bytes(mv[off:off + 16])
            ent = id_set.get(chunk)
            if ent is not None:
                out.append(Hit(koff, key, off, chunk, ent.line_id, ent.kind,
                               off - koff))
    return out


def dominant_delta(hits: list[Hit], min_count: int = 2) -> tuple[int, int] | None:
    """Most common (delta) across hits, if seen >= min_count times.

    A repeated guid_off - key_off across many distinct lines is the fixed-stride
    signature of the resident binding record. Returns (delta, count) or None.
    """
    if not hits:
        return None
    counts = Counter(h.delta for h in hits)
    delta, count = counts.most_common(1)[0]
    if count < min_count:
        return None
    return delta, count


def sweep_bindings(buf, key_offsets: dict[int, int], id_set: dict[bytes, IdEntry],
                   delta: int) -> list[tuple[str, int, str]]:
    """At the fixed `delta`, read the GUID for every key hit; keep those in the set.

    Returns [(line_id, key, kind)] for each recovered binding (deduped on
    (line_id, key)). This is the recovered line->key map for everything resident.
    """
    n = len(buf)
    mv = memoryview(buf)
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int, str]] = []
    for koff, key in key_offsets.items():
        goff = koff + delta
        if goff < 0 or goff + 16 > n:
            continue
        ent = id_set.get(bytes(mv[goff:goff + 16]))
        if ent is None:
            continue
        k = (ent.line_id, key)
        if k in seen:
            continue
        seen.add(k)
        out.append((ent.line_id, key, ent.kind))
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class ScanResult:
    n_key_hits: int
    n_guid_hits: int
    delta: tuple[int, int] | None
    bindings: list[tuple[str, int, str]]
    exit_code: int


def run_scan(buf, key_set: dict[int, tuple[int, int]], id_set: dict[bytes, IdEntry],
             window: int, four_byte: bool = True) -> tuple[ScanResult, dict[int, int]]:
    key_offsets = find_key_offsets_aligned(buf, set(key_set), four_byte=four_byte)
    hits = collect_hits(buf, key_offsets, id_set, window)
    dd = dominant_delta(hits)
    if not key_offsets or not hits:
        # Distinguish "nothing resident" from "guids resident, no key nearby".
        code = EXIT_NOT_RESIDENT
        return ScanResult(len(key_offsets), len(hits), None, [], code), key_offsets
    if dd is None:
        return ScanResult(len(key_offsets), len(hits), None, [], EXIT_NO_DELTA), key_offsets
    bindings = sweep_bindings(buf, key_offsets, id_set, dd[0])
    code = EXIT_RECOVERED if bindings else EXIT_NO_DELTA
    return ScanResult(len(key_offsets), len(hits), dd, bindings, code), key_offsets


def write_table(path: str, bindings: list[tuple[str, int, str]],
                catalog: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["line_id", "stream_key", "hi32", "kind", "speaker_name", "subtitle_en"])
        for line_id, key, kind in sorted(bindings):
            row = catalog.get(line_id, {})
            w.writerow([line_id, f"0x{key:016x}", f"0x{key >> 32:08x}", kind,
                        row.get("speaker_name", ""), row.get("subtitle_en", "")])


def _summary(res: ScanResult) -> str:
    lines = [
        "== HZD memscan ==",
        f"  key-hits  : {res.n_key_hits}  (valid stream keys resident, aligned)",
        f"  guid-hits : {res.n_guid_hits}  (key adjacent to a known GUID/uuid)",
    ]
    if res.delta:
        d, c = res.delta
        lines.append(f"  dominant delta : {d:+d} bytes (seen {c}x) -> record stride")
    elif res.n_guid_hits:
        lines.append("  dominant delta : NONE (no consistent guid<->key offset)")
        lines.append("  -> binding record is pointer-linked, not adjacent; "
                     "pivot to the Frida hook (Strategy B).")
    else:
        lines.append("  -> no relevant data resident; dump too early / wrong scene. "
                     "Reach a dialogue scene and dump again.")
    lines.append(f"  bindings recovered : {len(res.bindings)}")
    lines.append(f"  exit code : {res.exit_code}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", required=True, help="path to the process minidump (.dmp)")
    ap.add_argument("--ids", default=DEFAULT_IDS, help="line_ids.csv (GUID index)")
    ap.add_argument("--package", default=DEFAULT_PACKAGE, help="HZDR package dir")
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG,
                    help="catalog.csv for speaker/subtitle join (optional)")
    ap.add_argument("--table", default=None, help="output CSV of recovered bindings")
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--no-four-byte", action="store_true",
                    help="only scan 8-byte-aligned key slots (skip the +4 class)")
    args = ap.parse_args(argv)

    key_set = load_key_set(args.package, args.archive)
    id_set = load_id_set(args.ids)
    print(f"loaded {len(key_set)} stream keys, {len(id_set)} GUID/uuid ids", flush=True)

    with open(args.dump, "rb") as f:
        buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            res, _ = run_scan(buf, key_set, id_set, args.window,
                              four_byte=not args.no_four_byte)
            if args.table and res.bindings:
                catalog = load_catalog(args.catalog)
                write_table(args.table, res.bindings, catalog)
        finally:
            buf.close()

    print(_summary(res))
    if args.table and res.bindings:
        print(f"  wrote {len(res.bindings)} bindings -> {args.table}")
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
