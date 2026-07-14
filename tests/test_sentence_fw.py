"""HZD (Forbidden-West package) sentence-core parsing.

Oracle values read directly from the raw bytes of
localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences:
object [0] is SentenceResource name "MQ010_cut_Prologue_Dial_220", voice ref
"localized/voices/rost", linked to the LocalizedTextResource whose English
(index 0) string is the prologue naming-ceremony line spoken by Rost — see
EXPECT_PREFIX_SHA below for the oracle hash (no verbatim subtitle text here).
"""
import hashlib

from engine.sentence_core import Line
from games.hzd.sentence_fw import parse_sentences_fw, parse_sentence_ids

# sha256 of the expected subtitle prefix — oracle value without shipping the text
EXPECT_PREFIX_LEN = 46
EXPECT_PREFIX_SHA = "b0a644524b6cf764fcdd7d2cbaa0c6beee569148cc6aeef44bc5179b716f7913"


def test_namingceremony_extracts_lines(hzd_namingceremony_core_bytes):
    lines = parse_sentences_fw(hzd_namingceremony_core_bytes)
    assert all(isinstance(l, Line) for l in lines)
    # 96 RTTI objects in clean Sentence/Sound/Text triples -> 32 lines.
    assert len(lines) == 32


def test_namingceremony_rost_line(hzd_namingceremony_core_bytes):
    lines = parse_sentences_fw(hzd_namingceremony_core_bytes)
    hit = [l for l in lines if l.line_id == "MQ010_cut_Prologue_Dial_220"]
    assert len(hit) == 1
    line = hit[0]
    assert line.speaker_code == "localized/voices/rost"
    prefix = line.subtitle_en[:EXPECT_PREFIX_LEN]
    assert hashlib.sha256(prefix.encode("utf-8")).hexdigest() == EXPECT_PREFIX_SHA
    assert line.wem_path_en == ""  # HZD audio resolves via SENTENCE uuid (Phase 5/6)


def test_namingceremony_line_index_is_sequential(hzd_namingceremony_core_bytes):
    lines = parse_sentences_fw(hzd_namingceremony_core_bytes)
    assert [l.line_index for l in lines] == list(range(len(lines)))


def test_parse_sentence_ids_oracle_linkage(hzd_namingceremony_core_bytes):
    ids = parse_sentence_ids(hzd_namingceremony_core_bytes)
    hit = [r for r in ids if r.line_id == "MQ010_cut_Prologue_Dial_225"]
    assert len(hit) == 1
    r = hit[0]
    # SoundResource GUID + SENTENCE uuid in raw on-disk byte order (the oracle).
    assert r.sound_resource_guid.hex() == "13f9532a11e94b6fbe26665e27bf4c3e"
    assert r.sentence_uuid.hex() == "573fa322aed14fdcbf932025218ff6c4"

