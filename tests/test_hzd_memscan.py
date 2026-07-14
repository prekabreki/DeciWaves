"""Tests for the HZD runtime memory scanner (tools/hzd_memscan.py).

Synthetic dumps: several distinct GUIDs each followed at a FIXED stride by their
stream key, embedded in junk. Asserts the dominant delta is detected, every record
is recovered and joined by line_id, and the pointer-linked case signals no delta.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hzd_memscan as ms


# A tiny fake id-set + key-set, structured like the real ones.
LINES = [
    ("MQ010_cut_Prologue_Dial_225", bytes.fromhex(ms.ORACLE_GUID_HEX),
     bytes.fromhex("573fa322aed14fdcbf932025218ff6c4"), ms.ORACLE_KEY),
    ("LINE_two", bytes(range(16)), bytes(range(16, 32)), 0x1122334405030200),
    ("LINE_three", bytes(range(32, 48)), bytes(range(48, 64)), 0xAABBCCDD06030100),
]


def _id_set():
    out = {}
    for lid, guid, uuid, _key in LINES:
        out[guid] = ms.IdEntry(lid, "guid")
        out[uuid] = ms.IdEntry(lid, "uuid")
    return out


def _key_set():
    # value: (offset, length) -- unused by the scan logic but mirrors the real shape.
    return {key: (0, 0) for _lid, _g, _u, key in LINES}


# --- low-level scan primitives ------------------------------------------------
def test_find_key_offsets_8_aligned():
    key = ms.ORACLE_KEY
    buf = b"\x00" * 16 + struct.pack("<Q", key) + b"\x00" * 16
    hits = ms.find_key_offsets(buf, {key}, stride=8)
    assert hits == {16: key}


def test_find_key_offsets_ignores_unaligned_and_unknown():
    key = ms.ORACLE_KEY
    # key placed at offset 4 (not 8-aligned) -> not found by the 8-aligned pass
    buf = b"\x00" * 4 + struct.pack("<Q", key) + b"\x00" * 16
    assert ms.find_key_offsets(buf, {key}, stride=8) == {}
    # unknown key never matches
    buf2 = struct.pack("<Q", 0xDEADBEEFCAFEBABE) + b"\x00" * 8
    assert ms.find_key_offsets(buf2, {key}, stride=8) == {}


def test_four_byte_alignment_union():
    key = ms.ORACLE_KEY
    # key at byte offset 4 (4-aligned, not 8-aligned)
    buf = b"\x00" * 4 + struct.pack("<Q", key) + b"\x00" * 8
    hits = ms.find_key_offsets_aligned(buf, {key}, four_byte=True)
    assert hits.get(4) == key


# --- record layout: GUID at fixed stride before the key ----------------------
def _record(guid: bytes, key: int) -> bytes:
    # layout: GUID(16) then two filler u32 then the key -> key is at delta -24 from
    # guid's start when anchored on the key. (We anchor scans on the key offset.)
    return guid + struct.pack("<II", 0, 0) + struct.pack("<Q", key)


def _build_dump():
    # three records of identical shape, separated by >window junk
    junk = b"\x5A" * 700
    blob = junk
    for _lid, guid, _uuid, key in LINES:
        blob += _record(guid, key) + junk
    # pad to 8-byte alignment so keys land on aligned slots
    pad = (-len(blob)) % 8
    return (b"\x00" * 8) + blob + (b"\x00" * pad)


def test_run_scan_recovers_all_records_with_dominant_delta():
    buf = _build_dump()
    res, key_offsets = ms.run_scan(buf, _key_set(), _id_set(), window=512)
    assert res.exit_code == ms.EXIT_RECOVERED
    # every key resident -> 3 key hits
    assert res.n_key_hits == len(LINES)
    # dominant delta is guid_off - key_off = -24 for all three
    assert res.delta is not None
    assert res.delta[0] == -24
    assert res.delta[1] == len(LINES)
    # all three lines recovered and joined by line_id
    got = {(lid, key) for lid, key, _kind in res.bindings}
    assert got == {(lid, key) for lid, _g, _u, key in LINES}


def test_sweep_table_joins_catalog(tmp_path):
    buf = _build_dump()
    res, _ = ms.run_scan(buf, _key_set(), _id_set(), window=512)
    catalog = {"MQ010_cut_Prologue_Dial_225":
               {"speaker_name": "aloy", "subtitle_en": "hello"}}
    out = tmp_path / "bindings.csv"
    ms.write_table(str(out), res.bindings, catalog)
    text = out.read_text(encoding="utf-8")
    assert "line_id,stream_key,hi32,kind,speaker_name,subtitle_en" in text
    assert "MQ010_cut_Prologue_Dial_225" in text
    assert "0x3e0f9d43" in text   # hi32 of the oracle key
    assert "aloy" in text


def test_no_consistent_delta_signals_exit_1():
    # GUIDs and keys both resident but scattered with DIFFERENT, non-repeating deltas
    g0 = LINES[0][1]
    g1 = LINES[1][1]
    k0 = LINES[0][3]
    k1 = LINES[1][3]
    buf = (b"\x00" * 8
           + g0 + b"\x11" * 8 + struct.pack("<Q", k0)            # delta -24
           + b"\x22" * 64
           + struct.pack("<Q", k1) + b"\x33" * 40 + g1           # delta +48
           )
    pad = (-len(buf)) % 8
    buf += b"\x00" * pad
    res, _ = ms.run_scan(buf, _key_set(), _id_set(), window=512)
    # two key hits, two guid hits, but each delta seen only once -> no dominant
    assert res.n_guid_hits >= 1
    assert res.delta is None
    assert res.exit_code == ms.EXIT_NO_DELTA


def test_no_data_resident_signals_exit_2():
    buf = b"\x77" * 4096   # no keys, no guids
    res, _ = ms.run_scan(buf, _key_set(), _id_set(), window=512)
    assert res.n_key_hits == 0
    assert res.n_guid_hits == 0
    assert res.bindings == []
    assert res.exit_code == ms.EXIT_NOT_RESIDENT


def test_pure_python_fallback_matches_numpy():
    # the dependency-light path must find the same 8-aligned key offsets
    key = ms.ORACLE_KEY
    buf = b"\x00" * 16 + struct.pack("<Q", key) + b"\x00" * 16
    assert ms._find_key_offsets_py(buf, {key}, stride=8) == {16: key}


def test_oracle_constants_preserved():
    # the documented oracle is still the reference line
    assert ms.ORACLE_GUID_HEX == "13f9532a11e94b6fbe26665e27bf4c3e"
    assert ms.ORACLE_KEY == 0x3E0F9D4305030200
