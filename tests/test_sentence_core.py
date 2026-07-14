import hashlib
from unittest.mock import MagicMock, patch
from engine.sentence_core import parse_sentences, Line

PROVEN_EN = ("localized/sentences/ds_lines_terminal/lines_pr201/"
             "sentences_sentence_00a2c114-b35c-4f09-b6a3-f373e5946d74.wem.english")

# sha256 of the expected subtitle prefix — oracle value without shipping the text
EXPECT_PREFIX_LEN = 33
EXPECT_PREFIX_SHA = "f822f13ab31f1a4bd97710d0e14fc39ede186d33e5f850ac30718c643490f705"


def test_pr201_lines(pr201_core_bytes):
    lines = parse_sentences(pr201_core_bytes)
    assert len(lines) >= 70  # 77 sound objects; some lines may lack audio/text
    assert all(isinstance(l, Line) for l in lines)


def test_pr201_proven_line(pr201_core_bytes):
    lines = parse_sentences(pr201_core_bytes)
    hit = [l for l in lines if l.wem_path_en == PROVEN_EN]
    assert len(hit) == 1
    line = hit[0]
    assert line.speaker_code.endswith("vr1010_prp201a")
    prefix = line.subtitle_en[:EXPECT_PREFIX_LEN]
    assert hashlib.sha256(prefix.encode("utf-8")).hexdigest() == EXPECT_PREFIX_SHA
    assert line.line_id == "sentences_sentence_00a2c114-b35c-4f09-b6a3-f373e5946d74"


def test_cutscene_parses(cutscene_core_bytes):
    lines = parse_sentences(cutscene_core_bytes)
    assert len(lines) >= 1


# --- unit tests for review findings (no real fixtures needed) ---

def _make_core_with_sentence(language_list, wem_paths_list):
    """Build a minimal fake object graph for parse_sentences."""
    from pydecima.resources.SentenceGroupResource import SentenceGroupResource
    from pydecima.resources.LocalizedTextResource import LocalizedTextResource
    from pydecima.resources.LocalizedSimpleSoundResource import LocalizedSimpleSoundResource

    # Fake LocalizedTextResource
    fake_text_res = MagicMock(spec=LocalizedTextResource)
    fake_text_res.language = language_list

    # Fake LocalizedSimpleSoundResource
    fake_sound_res = MagicMock(spec=LocalizedSimpleSoundResource)
    fake_sound_res.wem_paths = wem_paths_list

    # Fake sentence
    fake_sent = MagicMock()
    fake_sent.voice = MagicMock()
    fake_sent.voice.path = "voice/speaker_x"
    fake_sent.text = MagicMock()
    fake_sent.text.type = 1  # non-zero = follow
    fake_sent.text.follow = MagicMock(return_value=fake_text_res)
    fake_sent.sound = MagicMock()
    fake_sent.sound.type = 1
    fake_sent.sound.follow = MagicMock(return_value=fake_sound_res)

    # Fake sref
    fake_sref = MagicMock()
    fake_sref.follow = MagicMock(return_value=fake_sent)

    # Fake group
    fake_group = MagicMock(spec=SentenceGroupResource)
    fake_group.name = "test_group"
    fake_group.sentences = [fake_sref]

    return fake_group, fake_sent, fake_sref


def _parse_with_fake_group(fake_group):
    """Call parse_sentences with a patched reader that injects fake_group."""
    from pydecima.resources.SentenceGroupResource import SentenceGroupResource

    def fake_read(stream, objs):
        objs["g"] = fake_group

    with patch("engine.sentence_core.reader.read_objects_from_stream", side_effect=fake_read):
        return parse_sentences(b"dummy")


def test_empty_language_list_yields_empty_subtitle():
    """Important 1a: empty language list must not raise — subtitle becomes ''."""
    fake_group, _, _ = _make_core_with_sentence(language_list=[], wem_paths_list=["a.wem.english"])
    lines = _parse_with_fake_group(fake_group)
    assert len(lines) == 1
    assert lines[0].subtitle_en == ""
    assert lines[0].wem_path_en == "a.wem.english"


def test_empty_wem_paths_yields_empty_wem():
    """Important 1b: empty wem_paths list must not raise — wem_path_en becomes ''."""
    fake_group, _, _ = _make_core_with_sentence(language_list=["Hello world"], wem_paths_list=[])
    lines = _parse_with_fake_group(fake_group)
    assert len(lines) == 1
    assert lines[0].wem_path_en == ""
    assert lines[0].subtitle_en == "Hello world"


def test_null_sentence_ref_calls_on_line_error():
    """Important 2: when sref.follow returns None, on_line_error must be called."""
    from pydecima.resources.SentenceGroupResource import SentenceGroupResource

    fake_sref = MagicMock()
    fake_sref.follow = MagicMock(return_value=None)  # unresolvable ref

    fake_group = MagicMock(spec=SentenceGroupResource)
    fake_group.name = "test_group"
    fake_group.sentences = [fake_sref]

    errors = []

    def fake_read(stream, objs):
        objs["g"] = fake_group

    with patch("engine.sentence_core.reader.read_objects_from_stream", side_effect=fake_read):
        lines = parse_sentences(b"dummy", on_line_error=lambda i, e: errors.append((i, e)))

    assert lines == []  # no row fabricated
    assert len(errors) == 1
    idx, exc = errors[0]
    assert idx == 0
    assert isinstance(exc, ValueError)
    assert "did not resolve" in str(exc)
