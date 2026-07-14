"""Regression tests for the DS:DC (DSPC) LocalizedTextResource + SentenceGroupResource
byte layouts. Synthetic objects only -- no game data, fully deterministic.

Both parsers used to abort the whole core on a layout mismatch:
  * LocalizedTextResource read a fixed 25 strings with a fixed 3 trailing bytes each, which
    desynced on the variable per-string padding (esp. the 1-byte 'special slot'), then read a
    garbage length and raised UnicodeDecodeError mid-binary.
  * SentenceGroupResource read the leading field as a hashed-string; when that flag == 1 it
    consumed a phantom 4-byte hash + 1 byte, reading `count` as ~500 million.
"""
import io
import struct

import deciwaves._vendor.pydecima.reader as reader
from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
from deciwaves._vendor.pydecima.resources.SentenceGroupResource import SentenceGroupResource
from deciwaves._vendor.pydecima.enums.ETextLanguages import ETextLanguages

LTR_HASH = 0x31BE502435317445
SGR_HASH = 0xC144982A3EE1E95D


def _wrap(type_hash, body):
    # Resource header = type_hash(8) + size(4) + uuid(16); object total = size + 12,
    # so the body occupies size - 16 bytes => size = len(body) + 16.
    uuid = bytes(range(16))
    return struct.pack('<QI', type_hash, len(body) + 16) + uuid + body


def _str_entry(text):
    b = text.encode('utf-8')
    return struct.pack('<H', len(b)) + b


def _ref(type_byte=1):
    return bytes([type_byte]) + bytes(16)  # ref type + 16-byte hash (type 1 = local)


def _parse_one(type_hash, body):
    # read_objects_from_stream asserts each object consumes exactly size+12, so a successful
    # parse here also proves the parser is byte-exact (no over/under-read).
    objs = {}
    reader.read_objects_from_stream(io.BytesIO(_wrap(type_hash, body)), objs)
    assert len(objs) == 1
    return next(iter(objs.values()))


# --- LocalizedTextResource ---------------------------------------------------------------

def test_ltr_variable_padding_and_special_slot():
    body = (_str_entry("Hello") + b"\x00\x00\x00"      # normal 3-byte padding
            + _str_entry("Bonjour") + b"\x00"           # 'special slot': only 1 trailing byte
            + _str_entry("あい")                # Japanese 'あい' (multibyte UTF-8)
            + b"\x00\x00\x00")
    res = _parse_one(LTR_HASH, body)                    # must NOT raise (byte-exact)
    assert isinstance(res, LocalizedTextResource)
    assert res.language[0] == "Hello"
    assert res.language[1] == "Bonjour"
    assert res.language[2] == "あい"
    assert len(res.language) >= len(ETextLanguages)     # padded for safe [i] access


def test_ltr_garbage_tail_does_not_abort_core():
    # A trailing word that scans as an out-of-range length must not raise; English survives.
    body = _str_entry("OnlyEnglish") + b"\x00\x00" + struct.pack('<H', 0xFFFF) + b"\x01\x02\x03"
    res = _parse_one(LTR_HASH, body)
    assert res.language[0] == "OnlyEnglish"


def test_ltr_english_only_object():
    res = _parse_one(LTR_HASH, _str_entry("<ignoresub>") + b"\x00\x00\x00")
    assert res.language[0] == "<ignoresub>"
    assert len(res.language) >= len(ETextLanguages)


# --- SentenceGroupResource ---------------------------------------------------------------

def test_sgr_flag1_reads_correct_count():
    # flag == 1 is the case the old parse_hashed_string path misread as name(1)+hash(4).
    body = struct.pack('<II', 1, 2) + _ref() + _ref()
    res = _parse_one(SGR_HASH, body)
    assert isinstance(res, SentenceGroupResource)
    assert res.group_flag == 1
    assert res.sentence_type is None
    assert len(res.sentences) == 2


def test_sgr_flag0_backwards_compatible():
    body = struct.pack('<II', 0, 3) + _ref() + _ref() + _ref()
    res = _parse_one(SGR_HASH, body)
    assert res.group_flag == 0
    assert len(res.sentences) == 3
