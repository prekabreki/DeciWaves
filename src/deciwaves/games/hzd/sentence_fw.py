"""Parse one HZD Remastered dialogue .core (Forbidden-West package format) into
voice-line rows.

HZD diverges from DS in two ways that rule out the pydecima DS path
(see .memories/hzd-structural-binding.md):

* Sentence cores are **flat** — a list of SentenceResource/Sound/Text objects with
  **no SentenceGroupResource** (the group lives in a separate higher-level core).
* FW resource type-hashes and byte layouts differ from both DS and original HZD.

So this is a self-contained tolerant byte parser (RTTI walk + length-prefix string
scan), in the spirit of the DS LocalizedSimpleSoundResource fix — size-exact by
construction, no fragile field-by-field alignment. It does not use pydecima.

Per object (each body begins with the object's 16-byte GUID):
* SentenceResource (0x632B89BD29A87E6B): u32-len+u32-hash internal name, a type-2
  path ref ``localized/voices/<speaker>``, and an embedded copy of the linked
  LocalizedTextResource's GUID.
* LocalizedTextResource (0xFADA0E21A656D537): u16-length-prefixed strings per
  language, **English at index 0**.
* LocalizedSimpleSoundResource (0x4AFD36F67D7E8C76): keyed by ``SENTENCE_<uuid>``;
  carries no literal ``.wem`` path (HZD audio is resolved separately, Phase 5/6).
"""
from __future__ import annotations
import re
import struct
from dataclasses import dataclass

from deciwaves.engine.sentence_core import Line

SENTENCE_RESOURCE = 0x632B89BD29A87E6B
LOCALIZED_TEXT_RESOURCE = 0xFADA0E21A656D537
LOCALIZED_SIMPLE_SOUND_RESOURCE = 0x4AFD36F67D7E8C76

_VOICE_PREFIX = b"localized/voices/"
# SENTENCE_<dashed-uuid> string keying a LocalizedSimpleSoundResource to its sentence.
_SENTENCE_UUID_RE = re.compile(rb"SENTENCE_([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})")


def _rtti_walk(buf: bytes) -> list[tuple[int, bytes]]:
    """Yield (leading_type_hash, body_bytes) for each top-level RTTI object.

    body_bytes is the object's ``size`` payload (which starts with its 16-byte
    GUID). Stops at the first truncated header/body rather than raising.
    """
    pos, n = 0, len(buf)
    out: list[tuple[int, bytes]] = []
    while pos + 12 <= n:
        type_hash, size = struct.unpack_from("<QI", buf, pos)
        end = pos + 12 + size
        if end > n:
            break
        out.append((type_hash, buf[pos + 12: end]))
        pos = end
    return out


def _read_english(text_body: bytes) -> str:
    """First (index-0 / English) u16-length-prefixed string, after the 16B GUID."""
    if len(text_body) < 18:
        return ""
    ln = struct.unpack_from("<H", text_body, 16)[0]
    return text_body[18:18 + ln].decode("utf-8", "replace")


def _read_name(sent_body: bytes) -> str:
    """Internal name: u32 len + u32 hash + string, immediately after the 16B GUID."""
    if len(sent_body) < 24:
        return ""
    ln = struct.unpack_from("<I", sent_body, 16)[0]
    if ln <= 0 or 24 + ln > len(sent_body):
        return ""
    return sent_body[24:24 + ln].decode("utf-8", "replace")


def _read_voice(sent_body: bytes) -> str:
    """Speaker path from the type-2 ref (u32 len + u32 hash + path).

    Uses the length prefix (8 bytes before the path) for an exact, overrun-proof
    slice rather than a greedy character-class scan.
    """
    idx = sent_body.find(_VOICE_PREFIX)
    if idx < 8:
        return ""
    ln = struct.unpack_from("<I", sent_body, idx - 8)[0]
    if 0 < ln <= len(sent_body) - idx:
        return sent_body[idx:idx + ln].decode("utf-8", "replace")
    return ""


def parse_sentences_fw(core_bytes: bytes, on_line_error=None) -> list[Line]:
    objs = _rtti_walk(core_bytes)

    # First pass: index LocalizedTextResources by their GUID -> English subtitle.
    texts: dict[bytes, str] = {}
    for type_hash, body in objs:
        if type_hash == LOCALIZED_TEXT_RESOURCE and len(body) >= 16:
            texts[body[:16]] = _read_english(body)

    # Second pass: one Line per SentenceResource, in file order.
    lines: list[Line] = []
    index = 0
    for type_hash, body in objs:
        if type_hash != SENTENCE_RESOURCE:
            continue
        i = index
        index += 1
        try:
            name = _read_name(body)
            speaker = _read_voice(body)
            subtitle = ""
            for guid, english in texts.items():
                if guid in body:
                    subtitle = english
                    break
            line_id = name or f"sentence#{i}"
            # wem_path_en deferred: HZD audio resolves via SENTENCE uuid (Phase 5/6).
            lines.append(Line(line_id, i, speaker, subtitle, ""))
        except Exception as exc:  # fail-soft per line, like the DS parser
            if on_line_error:
                on_line_error(i, exc)
            continue
    return lines


def _dashed_uuid_to_raw(dashed: bytes) -> bytes:
    """`573fa322-aed1-4fdc-bf93-2025218ff6c4` -> raw 16 bytes (on-disk order).

    Verified against the oracle: the dashed SENTENCE_<uuid> string is the exact
    on-disk byte order of the SentenceResource's leading 16-byte GUID (no
    Decima big-endian shuffle), so we just strip dashes and unhex.
    """
    return bytes.fromhex(dashed.replace(b"-", b"").decode("ascii"))


@dataclass(frozen=True)
class LineIds:
    """Per-line identity needed to recover the runtime stream binding."""
    line_id: str
    line_index: int
    sound_resource_guid: bytes   # raw 16B, on-disk order (== oracle 13f9532a...)
    sentence_uuid: bytes         # raw 16B, on-disk order (== oracle 573fa322...)


@dataclass(frozen=True)
class LineMedia:
    """Per-line ATRAC9 media metadata extracted from LocalizedSimpleSoundResource."""
    line_id: str
    line_index: int
    a_bytes: int    # encoded ATRAC9 .wem byte-length (== locator stream length)
    b_samples: int  # decoded sample count (B/A ≈ 5.3 for 72kbps 48kHz mono ATRAC9)


_SOUND_BLOCK_HDR = bytes.fromhex("ff0f")  # precedes the 12×62-byte lang-entry block

# The byte AFTER `ff 0f` is a per-resource entry COUNT (observed 0x0d, 0x11, 0x09, …),
# NOT part of the marker. The old 3-byte `ff 0f 0d` matched only count==13 resources and
# silently dropped ~1,109 story lines (count 0x11/0x09/…); matching just `ff 0f` recovers
# them. The 3d lang-entry sits at the `ff 0f` start + 21 regardless of the count byte
# (empirically verified against the oracle MQ010_cut_Prologue_Dial_225: A=1338916, and
# across 65 sound bodies spanning the 0x0d and 0x11 counts).
_LANG_ENTRY_OFFSET = 21


def _read_media_ab(sound_body: bytes):
    """Return (a_bytes, b_samples) from the first per-language entry, or None.

    Entry layout: 3d (1B) · u32 A (encoded byte-len) · u32 B (sample-count) · …
    A and B are ~constant across the 12 per-language slots; we take the first slot.

    `ff 0f` can appear coincidentally before the real block, so scan forward and
    accept the first occurrence whose +21 byte is the 0x3d entry tag.
    """
    start = 0
    while True:
        h = sound_body.find(_SOUND_BLOCK_HDR, start)
        if h < 0:
            return None
        entry = h + _LANG_ENTRY_OFFSET  # first 62-byte language entry
        if entry + 9 <= len(sound_body) and sound_body[entry] == 0x3D:
            a, b = struct.unpack_from("<II", sound_body, entry + 1)
            return a, b
        start = h + 1


def parse_sentence_media(core_bytes: bytes, on_line_error=None) -> list[LineMedia]:
    """One LineMedia per SentenceResource, in file order, with ATRAC9 A/B fields.

    Joins by sentence uuid (same linkage as parse_sentence_ids) rather than by list
    position, so an orphan sound resource — one whose uuid has no matching sentence —
    cannot silently shift A/B values onto the wrong line.
    """
    ids = parse_sentence_ids(core_bytes, on_line_error=on_line_error)

    # Build uuid -> sound-body index (same walk as parse_sentence_ids, reusing the
    # existing _SENTENCE_UUID_RE constant and _dashed_uuid_to_raw helper).
    sounds_by_uuid: dict[bytes, bytes] = {}
    for type_hash, body in _rtti_walk(core_bytes):
        if type_hash != LOCALIZED_SIMPLE_SOUND_RESOURCE or len(body) < 16:
            continue
        m = _SENTENCE_UUID_RE.search(body)
        if not m:
            continue
        try:
            uuid_raw = _dashed_uuid_to_raw(m.group(1))
        except ValueError:
            continue
        sounds_by_uuid.setdefault(uuid_raw, body)

    out: list[LineMedia] = []
    for li in ids:
        body = sounds_by_uuid.get(li.sentence_uuid)
        if body is None:
            if on_line_error:
                on_line_error(li.line_id, "no sound body for sentence uuid")
            continue
        ab = _read_media_ab(body)
        if ab is None:
            if on_line_error:
                on_line_error(li.line_id, "no (A,B) block")
            continue
        out.append(LineMedia(li.line_id, li.line_index, ab[0], ab[1]))
    return out


def parse_sentence_ids(core_bytes: bytes, on_line_error=None) -> list[LineIds]:
    """One LineIds per SentenceResource, in file order, joined to its sound GUID.

    Linkage (verified on the oracle MQ010_cut_Prologue_Dial_225):
    * SentenceResource (0x632B...) body[:16] == its SENTENCE uuid (raw on-disk).
    * Its name (u32 len+hash, after the 16B GUID) == the catalog ``line_id``.
    * The matching LocalizedSimpleSoundResource (0x4AFD...) carries the same uuid
      as a ``SENTENCE_<dashed-uuid>`` string; that object's body[:16] is the
      SoundResource GUID whose audio lives in package.01.00.core.stream.

    line_index mirrors ``parse_sentences_fw`` (Nth SentenceResource), so rows join
    1:1 to catalog.csv by (line_id) and order matches by index.
    """
    objs = _rtti_walk(core_bytes)

    # Index sound GUIDs by the sentence uuid they reference.
    guid_by_uuid: dict[bytes, bytes] = {}
    for type_hash, body in objs:
        if type_hash != LOCALIZED_SIMPLE_SOUND_RESOURCE or len(body) < 16:
            continue
        m = _SENTENCE_UUID_RE.search(body)
        if not m:
            continue
        try:
            uuid_raw = _dashed_uuid_to_raw(m.group(1))
        except ValueError:
            continue
        guid_by_uuid.setdefault(uuid_raw, body[:16])

    out: list[LineIds] = []
    index = 0
    for type_hash, body in objs:
        if type_hash != SENTENCE_RESOURCE:
            continue
        i = index
        index += 1
        try:
            if len(body) < 16:
                continue
            sentence_uuid = body[:16]
            name = _read_name(body)
            line_id = name or f"sentence#{i}"
            sound_guid = guid_by_uuid.get(sentence_uuid)
            if sound_guid is None:
                if on_line_error:
                    on_line_error(i, ValueError("no sound resource for sentence uuid"))
                continue
            out.append(LineIds(line_id, i, sound_guid, sentence_uuid))
        except Exception as exc:  # fail-soft per line
            if on_line_error:
                on_line_error(i, exc)
            continue
    return out
