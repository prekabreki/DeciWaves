"""Synthetic-bytes fixture for the DS:DC sentence-parsing pipeline
(`deciwaves.engine.sentence_core.parse_sentences`, over the real
`deciwaves._vendor.pydecima.reader.read_objects_from_stream`).

`test_sentence_core.py`'s byte-level tests (`test_pr201_lines`,
`test_pr201_proven_line`, `test_cutscene_parses`) all depend on
`pr201_core_bytes`/`cutscene_core_bytes` -- real `.core` bytes extracted from a
DS:DC install, gitignored under `out/`, so those tests skip cleanly in CI. Its
other tests (`test_empty_language_list_yields_empty_subtitle` etc.) cover
`parse_sentences`'s internal edge cases, but do so by patching
`reader.read_objects_from_stream` with a `MagicMock` group -- the real
pydecima object-stream reader and the DSPC resource byte layouts are never
exercised.

This file closes that gap the same way `tests/test_dspc_layout.py` already
does for individual resource byte layouts (its `_wrap`/`_str_entry`/`_ref`
helpers), but one level up: it hand-builds a complete, valid DSPC `.core`
object stream -- one `LocalizedTextResource`, one `LocalizedSimpleSoundResource`,
one `SentenceResource`, one `SentenceGroupResource`, wired together with real
type-1 (in-stream, hash-only) `Ref`s -- and runs `parse_sentences()` over it
completely unmocked, all the way through the real
`reader.read_objects_from_stream`. Placeholder text only (no game prose).

Object framing (`Resource.__init__`): u64 type_hash, u32 size, 16-byte uuid,
then `size - 16` body bytes; `read_objects_from_stream` asserts each object
consumes exactly `size + 12` bytes, so a successful parse here is byte-exact
by construction, not merely "didn't crash".
"""
import struct

from deciwaves.engine.sentence_core import parse_sentences

LTR_HASH = 0x31BE502435317445           # LocalizedTextResource
SENTENCE_HASH = 0xAD7F486B5DD745A4      # SentenceResource
GROUP_HASH = 0xC144982A3EE1E95D         # SentenceGroupResource
SOUND_HASH = 0x859E0AC074117955         # LocalizedSimpleSoundResource

U_TEXT = bytes([1]) * 16
U_SOUND = bytes([2]) * 16
U_SENT = bytes([3]) * 16
U_SENT_2 = bytes([3]) * 15 + bytes([4])
U_GROUP = bytes([5]) * 16

WEM_PATH = ("localized/sentences/synthetic_test_group/"
            "sentences_sentence_11111111-2222-3333-4444-555555555555.wem.english")
WEM_PATH_2 = ("localized/sentences/synthetic_test_group/"
              "sentences_sentence_66666666-7777-8888-9999-000000000000.wem.english")
SUBTITLE = "Hello, this is a synthetic placeholder test line."
SUBTITLE_2 = "This is the second synthetic placeholder line."


def _wrap(type_hash, uuid, body):
    assert len(uuid) == 16
    return struct.pack('<QI', type_hash, len(body) + 16) + uuid + body


def _str_entry(text):
    b = text.encode('utf-8')
    return struct.pack('<H', len(b)) + b


def _ref_none():
    return bytes([0])


def _ref_local(uuid):
    """Type 1: hash-only ref, resolved against the in-memory object dict --
    no filesystem access (Ref.follow only touches game_root for type 2/3)."""
    assert len(uuid) == 16
    return bytes([1]) + uuid


def _ref_voice_path(path):
    """Type 2: hash + parse_hashed_string path. sentence_core reads
    `sent.voice.path` directly off the Ref (never calls `.follow()`), so the
    16-byte hash is never resolved and can be arbitrary."""
    path_bytes = path.encode('ascii')
    return bytes([2]) + bytes(16) + struct.pack('<I', len(path_bytes)) + bytes(4) + path_bytes


def _localized_text_resource(uuid, english_text):
    body = _str_entry(english_text) + b"\x00\x00\x00"
    return _wrap(LTR_HASH, uuid, body)


def _localized_simple_sound_resource(uuid, wem_path_en):
    wem_bytes = wem_path_en.encode('utf-8')
    assert 80 <= len(wem_bytes) <= 300, "must fall in the scanner's plausible-length window"
    body = struct.pack('<I', len(wem_bytes)) + wem_bytes
    return _wrap(SOUND_HASH, uuid, body)


def _sentence_resource(uuid, sound_uuid, text_uuid, voice_path):
    body = (
        struct.pack('<Ibb', 0, 0, 0)   # unk_int, unk_byte_1, unk_byte_2
        + _ref_local(sound_uuid)
        + _ref_none()                   # animation
        + _ref_local(text_uuid)
        + _ref_voice_path(voice_path)
    )
    return _wrap(SENTENCE_HASH, uuid, body)


def _sentence_group_resource(uuid, sentence_uuids):
    body = struct.pack('<II', 0, len(sentence_uuids))
    for u in sentence_uuids:
        body += _ref_local(u)
    return _wrap(GROUP_HASH, uuid, body)


def _one_line_core_bytes():
    return b"".join([
        _localized_text_resource(U_TEXT, SUBTITLE),
        _localized_simple_sound_resource(U_SOUND, WEM_PATH),
        _sentence_resource(U_SENT, U_SOUND, U_TEXT, "voice/synthetic_speaker"),
        _sentence_group_resource(U_GROUP, [U_SENT]),
    ])


def test_single_line_round_trip():
    lines = parse_sentences(_one_line_core_bytes())
    assert len(lines) == 1
    line = lines[0]
    assert line.speaker_code == "voice/synthetic_speaker"
    assert line.subtitle_en == SUBTITLE
    assert line.wem_path_en == WEM_PATH
    assert line.line_id == "sentences_sentence_11111111-2222-3333-4444-555555555555"
    assert line.line_index == 0


def test_two_lines_in_one_group_preserve_order():
    core_bytes = b"".join([
        _localized_text_resource(U_TEXT, SUBTITLE),
        _localized_simple_sound_resource(U_SOUND, WEM_PATH),
        _sentence_resource(U_SENT, U_SOUND, U_TEXT, "voice/speaker_one"),
        _localized_text_resource(bytes([9]) * 16, SUBTITLE_2),
        _localized_simple_sound_resource(bytes([10]) * 16, WEM_PATH_2),
        _sentence_resource(U_SENT_2, bytes([10]) * 16, bytes([9]) * 16, "voice/speaker_two"),
        _sentence_group_resource(U_GROUP, [U_SENT, U_SENT_2]),
    ])
    lines = parse_sentences(core_bytes)
    assert [l.line_index for l in lines] == [0, 1]
    assert lines[0].speaker_code == "voice/speaker_one"
    assert lines[0].subtitle_en == SUBTITLE
    assert lines[1].speaker_code == "voice/speaker_two"
    assert lines[1].subtitle_en == SUBTITLE_2


def test_unresolvable_sentence_ref_reports_error_not_crash():
    """A group referencing a uuid with no matching SentenceResource in the
    stream must fail-soft (on_line_error called, no row fabricated) rather
    than raising out of parse_sentences. This is a type-1 (hash-only) Ref with
    no matching object in the dict and no `path` fallback, so the REAL
    `Ref.follow` (pydecima, unmocked) raises "Resource not in list" itself --
    a different, lower-layer failure than sentence_core's own
    sentence-ref-resolved-to-None guard (already covered by a MagicMock in
    test_sentence_core.py::test_null_sentence_ref_calls_on_line_error)."""
    dangling_uuid = bytes([0xFF]) * 16
    core_bytes = _sentence_group_resource(U_GROUP, [dangling_uuid])
    errors = []
    lines = parse_sentences(core_bytes, on_line_error=lambda i, e: errors.append((i, e)))
    assert lines == []
    assert len(errors) == 1
    idx, exc = errors[0]
    assert idx == 0
    assert "Resource not in list" in str(exc)


def test_japanese_only_subtitle_yields_empty_not_wrong_language():
    """When the English slot is genuinely absent and the scanner's only
    string is non-Latin, sentence_core's is_plausibly_english guard must
    still produce an empty subtitle_en, not surface the wrong-language text --
    exercised here through the real byte scanner, not a fake language list."""
    japanese_only = "サムライ"
    core_bytes = b"".join([
        _localized_text_resource(U_TEXT, japanese_only),
        _localized_simple_sound_resource(U_SOUND, WEM_PATH),
        _sentence_resource(U_SENT, U_SOUND, U_TEXT, "voice/synthetic_speaker"),
        _sentence_group_resource(U_GROUP, [U_SENT]),
    ])
    lines = parse_sentences(core_bytes)
    assert len(lines) == 1
    assert lines[0].subtitle_en == ""
    assert lines[0].wem_path_en == WEM_PATH
