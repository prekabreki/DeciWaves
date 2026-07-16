"""Synthetic-bytes fixture for the HZD-Remastered / Forbidden-West-package
sentence parser (`deciwaves.games.hzd.sentence_fw`).

`tests/test_sentence_fw.py` depends entirely on `hzd_namingceremony_core_bytes`,
real bytes extracted from an HZD Remastered install and gitignored under
`out/hzd/` -- so all 4 of its tests skip cleanly in CI without that install.
`sentence_fw.py` is a self-contained, hand-rolled RTTI-walk + length-prefix
byte scanner (no pydecima, no external decoder) with its exact byte layout
fully documented in its own module docstring, so it is directly synthesizable
-- same technique as `tests/test_dsar_archive.py`.

Builds a minimal set of RTTI objects by hand (one SentenceResource, one
LocalizedTextResource, one LocalizedSimpleSoundResource, wired together via
the same embedded-GUID / `SENTENCE_<uuid>` string linkage the real format
uses) and runs `parse_sentences_fw`, `parse_sentence_ids`, and
`parse_sentence_media` completely unmocked. Placeholder text only (no game
prose).
"""
import struct
import uuid

from deciwaves.games.hzd.sentence_fw import (
    LOCALIZED_SIMPLE_SOUND_RESOURCE,
    LOCALIZED_TEXT_RESOURCE,
    SENTENCE_RESOURCE,
    parse_sentence_ids,
    parse_sentence_media,
    parse_sentences_fw,
)

_VOICE_PREFIX = b"localized/voices/"


def _wrap(type_hash, body):
    """RTTI-walk framing: u64 type_hash, u32 size, then `size` body bytes
    (the body itself opens with the object's own 16-byte GUID)."""
    return struct.pack('<QI', type_hash, len(body)) + body


def _dashed(raw_guid: bytes) -> str:
    return str(uuid.UUID(bytes=raw_guid))


def _sentence_body(sentence_uuid, name, text_guid, voice_path):
    name_bytes = name.encode('utf-8')
    voice_bytes = voice_path.encode('utf-8')
    assert voice_bytes.startswith(_VOICE_PREFIX)
    return (
        sentence_uuid
        + struct.pack('<II', len(name_bytes), 0xAAAAAAAA) + name_bytes
        + text_guid                                            # embedded raw-GUID linkage
        + struct.pack('<II', len(voice_bytes), 0xBBBBBBBB) + voice_bytes
    )


def _text_body(text_guid, english):
    english_bytes = english.encode('utf-8')
    return text_guid + struct.pack('<H', len(english_bytes)) + english_bytes


def _sound_body(sound_guid, sentence_uuid, a_bytes=1_000_000, b_samples=200_000, count_byte=0x0D):
    dashed = _dashed(sentence_uuid).encode('ascii')
    # 21 bytes from the "ff 0f" marker start to the 0x3D lang-entry tag (see
    # sentence_fw._LANG_ENTRY_OFFSET): 2 (ff 0f) + 1 (count) + 18 filler.
    media_prefix = b"\xff\x0f" + bytes([count_byte]) + bytes(18)
    media_entry = bytes([0x3D]) + struct.pack('<II', a_bytes, b_samples)
    return sound_guid + b"SENTENCE_" + dashed + media_prefix + media_entry


SENTENCE_UUID = bytes(range(16))
TEXT_GUID = bytes([0x11]) * 16
SOUND_GUID = bytes([0xAA]) * 16
NAME = "MQ_synthetic_test_line"
VOICE_PATH = "localized/voices/synthetic_speaker"
ENGLISH_TEXT = "Hello, this is a synthetic placeholder subtitle."


def _one_line_core_bytes(a_bytes=1_000_000, b_samples=200_000):
    return b"".join([
        _wrap(SENTENCE_RESOURCE, _sentence_body(SENTENCE_UUID, NAME, TEXT_GUID, VOICE_PATH)),
        _wrap(LOCALIZED_TEXT_RESOURCE, _text_body(TEXT_GUID, ENGLISH_TEXT)),
        _wrap(LOCALIZED_SIMPLE_SOUND_RESOURCE, _sound_body(SOUND_GUID, SENTENCE_UUID, a_bytes, b_samples)),
    ])


def test_single_line_extracts_name_speaker_subtitle():
    lines = parse_sentences_fw(_one_line_core_bytes())
    assert len(lines) == 1
    line = lines[0]
    assert line.line_id == NAME
    assert line.speaker_code == VOICE_PATH
    assert line.subtitle_en == ENGLISH_TEXT
    assert line.wem_path_en == ""  # HZD audio resolves via SENTENCE uuid, not a literal path
    assert line.line_index == 0


def test_line_index_sequential_across_two_sentences():
    second_uuid = bytes([0x22]) * 16
    second_text_guid = bytes([0x33]) * 16
    core_bytes = b"".join([
        _wrap(SENTENCE_RESOURCE, _sentence_body(SENTENCE_UUID, NAME, TEXT_GUID, VOICE_PATH)),
        _wrap(LOCALIZED_TEXT_RESOURCE, _text_body(TEXT_GUID, ENGLISH_TEXT)),
        _wrap(SENTENCE_RESOURCE, _sentence_body(second_uuid, "MQ_synthetic_second", second_text_guid,
                                                 "localized/voices/second_speaker")),
        _wrap(LOCALIZED_TEXT_RESOURCE, _text_body(second_text_guid, "Second synthetic placeholder line.")),
    ])
    lines = parse_sentences_fw(core_bytes)
    assert [l.line_index for l in lines] == [0, 1]
    assert [l.line_id for l in lines] == [NAME, "MQ_synthetic_second"]
    assert lines[1].speaker_code == "localized/voices/second_speaker"
    assert lines[1].subtitle_en == "Second synthetic placeholder line."


def test_parse_sentence_ids_links_sound_guid_to_sentence_uuid():
    ids = parse_sentence_ids(_one_line_core_bytes())
    assert len(ids) == 1
    r = ids[0]
    assert r.line_id == NAME
    assert r.line_index == 0
    assert r.sentence_uuid == SENTENCE_UUID
    assert r.sound_resource_guid == SOUND_GUID


def test_parse_sentence_media_reads_a_b_fields():
    media = parse_sentence_media(_one_line_core_bytes(a_bytes=1_338_916, b_samples=253_000))
    assert len(media) == 1
    m = media[0]
    assert m.line_id == NAME
    assert m.a_bytes == 1_338_916
    assert m.b_samples == 253_000


def test_parse_sentence_ids_no_sound_resource_reports_error():
    """A SentenceResource with no matching LocalizedSimpleSoundResource
    (no SENTENCE_<uuid> string references its GUID) must fail-soft, not crash."""
    core_bytes = b"".join([
        _wrap(SENTENCE_RESOURCE, _sentence_body(SENTENCE_UUID, NAME, TEXT_GUID, VOICE_PATH)),
        _wrap(LOCALIZED_TEXT_RESOURCE, _text_body(TEXT_GUID, ENGLISH_TEXT)),
        # no LocalizedSimpleSoundResource at all
    ])
    errors = []
    ids = parse_sentence_ids(core_bytes, on_line_error=lambda i, e: errors.append((i, e)))
    assert ids == []
    assert len(errors) == 1
    assert errors[0][0] == 0


# ---------------------------------------------------------------------------
# Fallback `sentence#N` line-id namespacing (issue #47): a SentenceResource with no
# internal name gets `sentence#N`, unique only within its own core pre-#47 -- two
# different cores' Nth unnamed line collided on the exact same fallback id, and
# downstream dict-keyed-by-line_id consumers silently kept only the last one.
# ---------------------------------------------------------------------------

def _unnamed_line_core_bytes():
    """A single SentenceResource with an EMPTY internal name -- `_read_name` returns ""
    for a 0-length name field, so `line_id` falls through to the `sentence#N` path."""
    return b"".join([
        _wrap(SENTENCE_RESOURCE, _sentence_body(SENTENCE_UUID, "", TEXT_GUID, VOICE_PATH)),
        _wrap(LOCALIZED_TEXT_RESOURCE, _text_body(TEXT_GUID, ENGLISH_TEXT)),
        _wrap(LOCALIZED_SIMPLE_SOUND_RESOURCE, _sound_body(SOUND_GUID, SENTENCE_UUID)),
    ])


def test_fallback_id_named_lines_are_untouched_by_core_path():
    """A proper (non-fallback) id must never be namespaced -- only the sentence#N
    fallback path is core_path-dependent."""
    lines_a = parse_sentences_fw(_one_line_core_bytes(), core_path="core/a/sentences")
    lines_b = parse_sentences_fw(_one_line_core_bytes(), core_path="core/b/sentences")
    assert lines_a[0].line_id == lines_b[0].line_id == NAME


def test_fallback_id_differs_across_cores_for_the_same_index():
    """The actual bug (issue #47): index 0's fallback id in two DIFFERENT cores must no
    longer collide once each is namespaced by its own core_path."""
    id_a = parse_sentences_fw(_unnamed_line_core_bytes(), core_path="localized/sentences/a/sentences")
    id_b = parse_sentences_fw(_unnamed_line_core_bytes(), core_path="localized/sentences/b/sentences")
    assert id_a[0].line_id != id_b[0].line_id
    assert id_a[0].line_id.endswith("#sentence#0")
    assert id_b[0].line_id.endswith("#sentence#0")


def test_fallback_id_is_deterministic_for_the_same_core_path():
    """Namespacing must be stable across separate runs/processes (a hash of the core
    path, not e.g. Python's randomized str hash() or an object id)."""
    core_path = "localized/sentences/mq04/scene/sentences"
    first = parse_sentences_fw(_unnamed_line_core_bytes(), core_path=core_path)
    second = parse_sentences_fw(_unnamed_line_core_bytes(), core_path=core_path)
    assert first[0].line_id == second[0].line_id


def test_fallback_id_default_core_path_matches_pre_47_bare_form_when_unset():
    """Callers that don't pass core_path (e.g. direct unit tests of parsing logic) get
    a stable, harmless default rather than an error -- the namespace prefix is simply
    constant across such calls."""
    lines = parse_sentences_fw(_unnamed_line_core_bytes())
    assert lines[0].line_id.endswith("#sentence#0")


def test_parse_sentence_ids_fallback_id_is_also_namespaced():
    id_a = parse_sentence_ids(_unnamed_line_core_bytes(), core_path="a/sentences")
    id_b = parse_sentence_ids(_unnamed_line_core_bytes(), core_path="b/sentences")
    assert id_a[0].line_id != id_b[0].line_id


def test_parse_sentence_media_fallback_id_matches_parse_sentence_ids():
    """parse_sentence_media must use the exact same namespaced fallback id as
    parse_sentence_ids for the same core_path -- it's the single shared generator, not
    re-derived -- so the two stages' outputs join on line_id."""
    core_path = "localized/sentences/mq07/scene/sentences"
    ids = parse_sentence_ids(_unnamed_line_core_bytes(), core_path=core_path)
    media = parse_sentence_media(_unnamed_line_core_bytes(), core_path=core_path)
    assert media[0].line_id == ids[0].line_id
