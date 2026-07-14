import struct
import pytest
from games.hzd.wem_metadata import coverage_report
from games.hzd.sentence_fw import (
    parse_sentence_media,
    parse_sentence_ids,
    LineMedia,
    _rtti_walk,
    SENTENCE_RESOURCE,
    LOCALIZED_SIMPLE_SOUND_RESOURCE,
    _SOUND_BLOCK_HDR,
    _LANG_ENTRY_OFFSET,
)


def test_media_extracted_for_every_line(hzd_namingceremony_core_bytes):
    media = parse_sentence_media(hzd_namingceremony_core_bytes)
    ids = parse_sentence_ids(hzd_namingceremony_core_bytes)
    # one media record per line, aligned to the id parse
    assert len(media) == len(ids)
    assert [m.line_index for m in media] == [i.line_index for i in ids]


def test_media_values_are_plausible_atrac9(hzd_namingceremony_core_bytes):
    media = parse_sentence_media(hzd_namingceremony_core_bytes)
    for m in media:
        assert m.a_bytes > 0 and m.b_samples > 0
        # ATRAC9 48kHz mono ~72kbps => B/A ~5.3 (allow a wide band)
        assert 3.0 < (m.b_samples / m.a_bytes) < 8.0


def test_oracle_a_bytes_for_prologue_dial_225(hzd_namingceremony_core_bytes):
    """Regression guard: MQ010_cut_Prologue_Dial_225 must have a_bytes == 1338916."""
    media = parse_sentence_media(hzd_namingceremony_core_bytes)
    oracle = next((m for m in media if m.line_id == "MQ010_cut_Prologue_Dial_225"), None)
    if oracle is not None:
        assert oracle.a_bytes == 1338916, (
            f"oracle a_bytes mismatch: got {oracle.a_bytes}, expected 1338916"
        )


def _make_sentence_body(uuid16: bytes, name: str) -> bytes:
    """Minimal SentenceResource body: 16B GUID + u32 len + u32 hash + name."""
    name_b = name.encode("utf-8")
    return uuid16 + struct.pack("<II", len(name_b), 0) + name_b


def _make_sound_body(sentence_uuid16: bytes, a: int, b: int) -> bytes:
    """Minimal LocalizedSimpleSoundResource body containing a SENTENCE_<uuid> tag
    and a single lang-entry block with the given A and B values."""
    import uuid as _uuid_mod
    dashed = str(_uuid_mod.UUID(bytes=sentence_uuid16)).encode("ascii")
    sentence_tag = b"SENTENCE_" + dashed
    # Pad enough bytes before the sound-block header so entry fits.
    pad = b"\x00" * 32
    entry = bytes([0x3D]) + struct.pack("<II", a, b) + b"\x00" * 54  # 62-byte slot
    block = _SOUND_BLOCK_HDR + b"\x00" * (_LANG_ENTRY_OFFSET - len(_SOUND_BLOCK_HDR)) + entry
    return b"\x00" * 16 + sentence_tag + pad + block


def _frame(type_hash: int, body: bytes) -> bytes:
    return struct.pack("<QI", type_hash, len(body)) + body


def test_uuid_join_skips_orphan_sound():
    """An orphan sound (uuid not in any SentenceResource) must NOT shift A/B onto
    the next real sentence.  With the old positional zip this test would fail."""
    uuid_a = bytes.fromhex("aabbccdd" * 4)   # sentence A
    uuid_b = bytes.fromhex("11223344" * 4)   # sentence B  (real)
    uuid_orphan = bytes.fromhex("deadbeef" * 4)  # sound with no sentence

    sent_a = _make_sentence_body(uuid_a, "line_A")
    sent_b = _make_sentence_body(uuid_b, "line_B")
    sound_orphan = _make_sound_body(uuid_orphan, a=9999, b=99999)
    sound_b = _make_sound_body(uuid_b, a=1234, b=6543)
    sound_a = _make_sound_body(uuid_a, a=5678, b=30123)

    # File order: sentence_A, sentence_B, orphan_sound, sound_B, sound_A
    # Positional zip would pair sentence_A→orphan_sound and sentence_B→sound_B,
    # giving a_bytes=9999 for line_A (wrong).  UUID join must give 5678 and 1234.
    core = (
        _frame(SENTENCE_RESOURCE, sent_a)
        + _frame(SENTENCE_RESOURCE, sent_b)
        + _frame(LOCALIZED_SIMPLE_SOUND_RESOURCE, sound_orphan)
        + _frame(LOCALIZED_SIMPLE_SOUND_RESOURCE, sound_b)
        + _frame(LOCALIZED_SIMPLE_SOUND_RESOURCE, sound_a)
    )

    errors: list = []
    media = parse_sentence_media(core, on_line_error=lambda lid, e: errors.append((lid, e)))

    assert len(media) == 2, f"expected 2 media records, got {len(media)}"
    by_id = {m.line_id: m for m in media}
    assert by_id["line_A"].a_bytes == 5678, f"line_A a_bytes wrong: {by_id['line_A'].a_bytes}"
    assert by_id["line_B"].a_bytes == 1234, f"line_B a_bytes wrong: {by_id['line_B'].a_bytes}"


def test_media_recovered_for_variable_count_marker():
    """The byte after `ff 0f` is a per-resource entry COUNT (0x0d, 0x11, 0x09, ...),
    not a fixed 0x0d. A sound block led by `ff 0f 11` must still yield (A,B).
    Regression for the ~1,109 lines dropped by the old 3-byte `ff 0f 0d` marker."""
    import uuid as _u
    uuid16 = bytes.fromhex("12345678" * 4)
    sent = _make_sentence_body(uuid16, "line_var")
    tag = b"SENTENCE_" + str(_u.UUID(bytes=uuid16)).encode("ascii")
    entry = bytes([0x3D]) + struct.pack("<II", 4242, 21000) + b"\x00" * 54
    # lang-entry sits at the `ff 0f` start + 21; third byte 0x11 (count) is data.
    block = bytes.fromhex("ff0f11") + b"\x00" * (_LANG_ENTRY_OFFSET - 3) + entry
    body = b"\x00" * 16 + tag + b"\x00" * 16 + block
    core = _frame(SENTENCE_RESOURCE, sent) + _frame(LOCALIZED_SIMPLE_SOUND_RESOURCE, body)
    media = parse_sentence_media(core)
    assert len(media) == 1
    assert media[0].a_bytes == 4242 and media[0].b_samples == 21000


def test_media_skips_false_positive_ff0f():
    """A coincidental `ff 0f` before the real block (whose +21 is NOT 0x3d) must be
    skipped, and the real lang-entry deeper in the body recovered (Cause-2 lines)."""
    import uuid as _u
    uuid16 = bytes.fromhex("87654321" * 4)
    sent = _make_sentence_body(uuid16, "line_false")
    tag = b"SENTENCE_" + str(_u.UUID(bytes=uuid16)).encode("ascii")
    entry = bytes([0x3D]) + struct.pack("<II", 7777, 35000) + b"\x00" * 54
    real_block = bytes.fromhex("ff0f09") + b"\x00" * (_LANG_ENTRY_OFFSET - 3) + entry
    # decoy: `ff 0f` whose +21 byte is 0x00 (not 0x3d), placed before the real block.
    decoy = bytes.fromhex("ff0f00") + b"\x55" * 40
    body = b"\x00" * 16 + tag + decoy + real_block
    core = _frame(SENTENCE_RESOURCE, sent) + _frame(LOCALIZED_SIMPLE_SOUND_RESOURCE, body)
    media = parse_sentence_media(core)
    assert len(media) == 1
    assert media[0].a_bytes == 7777 and media[0].b_samples == 35000


def test_coverage_report_counts(tmp_path):
    meta = tmp_path / "wem-metadata.csv"
    meta.write_text("line_id,a_bytes,b_samples\nL1,100,530\nL2,200,1060\n")
    cat = tmp_path / "catalog.csv"
    cat.write_text(
        "line_id,core_path,line_index,category,scene,speaker_code,speaker_name,subtitle_en,wem_path_en,language\n"
        "L1,c,0,main_quest,s,sp,Sp,Hello there,,english\n"
        "L2,c,1,main_quest,s,sp,Sp,A line,,english\n"
        "L3,c,2,ambient,s,sp,Sp,,,english\n")
    rep = coverage_report(str(meta), str(cat))
    assert rep["story_lines"] == 2      # L3 is ambient/blank -> not story
    assert rep["with_ab"] == 2
    assert rep["coverage_pct"] == 100.0


def test_coverage_report_tolerates_catalog_missing_columns(tmp_path):
    """A partial/older/hand-edited catalog missing the category or subtitle_en column
    must degrade to 'not story' rather than crashing the #24 gate with a KeyError."""
    meta = tmp_path / "wem-metadata.csv"
    meta.write_text("line_id,a_bytes,b_samples\nL1,100,530\n")
    cat = tmp_path / "catalog.csv"
    # No 'category' column; 'subtitle_en' present for L1 only.
    cat.write_text(
        "line_id,subtitle_en\n"
        "L1,Hello there\n"
        "L2,\n")
    rep = coverage_report(str(meta), str(cat))   # must not raise
    assert rep["story_lines"] == 1               # L1 counts (has subtitle); L2 blank -> skipped
    assert rep["with_ab"] == 1


def test_coverage_report_zero_bytes_not_counted(tmp_path):
    """A metadata row with a_bytes=0 or b_samples=0 must NOT count as covered."""
    meta = tmp_path / "wem-metadata.csv"
    # L1: fully populated; L2: a_bytes=0 (incomplete); L3: b_samples=0 (incomplete)
    meta.write_text(
        "line_id,a_bytes,b_samples\n"
        "L1,100,530\n"
        "L2,0,1060\n"
        "L3,200,0\n"
    )
    cat = tmp_path / "catalog.csv"
    cat.write_text(
        "line_id,core_path,line_index,category,scene,speaker_code,speaker_name,subtitle_en,wem_path_en,language\n"
        "L1,c,0,main_quest,s,sp,Sp,Hello,,english\n"
        "L2,c,1,main_quest,s,sp,Sp,World,,english\n"
        "L3,c,2,main_quest,s,sp,Sp,Goodbye,,english\n"
    )
    rep = coverage_report(str(meta), str(cat))
    assert rep["story_lines"] == 3
    assert rep["with_ab"] == 1          # only L1 has both A and B > 0
    assert rep["coverage_pct"] == round(100.0 / 3, 1)
