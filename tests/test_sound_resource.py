import io
import pydecima.reader as reader
from pydecima.resources.LocalizedSimpleSoundResource import LocalizedSimpleSoundResource

PROVEN_EN = ("localized/sentences/ds_lines_terminal/lines_pr201/"
             "sentences_sentence_00a2c114-b35c-4f09-b6a3-f373e5946d74.wem.english")


def _parse(core_bytes):
    objs = {}
    reader.read_objects_from_stream(io.BytesIO(core_bytes), objs)
    return objs


def test_core_parses_without_error(pr201_core_bytes):
    objs = _parse(pr201_core_bytes)  # must NOT raise
    assert len(objs) > 100


def test_sound_objects_expose_wem_paths(pr201_core_bytes):
    objs = _parse(pr201_core_bytes)
    sounds = [o for o in objs.values() if isinstance(o, LocalizedSimpleSoundResource)]
    assert len(sounds) == 77
    for s in sounds:
        assert len(s.wem_paths) == 12
        assert s.wem_paths[0].endswith(".wem.english")


def test_proven_line_english_path_present(pr201_core_bytes):
    objs = _parse(pr201_core_bytes)
    all_en = {o.wem_paths[0] for o in objs.values()
              if isinstance(o, LocalizedSimpleSoundResource)}
    assert PROVEN_EN in all_en
