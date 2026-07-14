"""Tests for cutscene_audio: scene -> english Wwise voice-track stream paths.

Mechanism documented in .memories/cutscene-audio-per-scene-voice-track.md.
"""
import csv

from deciwaves.games.ds import cutscene_audio as ca
from conftest import DATA_DIR, OODLE_DLL


ROOT = "ds/sounds/wwise_cinematics_sound_resource"


# ---------------------------------------------------------------- pure: paths

def test_candidate_sound_cores_flat():
    cands = ca.candidate_sound_cores("sq_cs04_s01650")
    assert cands[0] == f"{ROOT}/cs04/sq_cs04_s01650/sq_cs04_s01650_sound"


def test_candidate_sound_cores_subcut_adds_nested_form():
    # Catalog scene names the cut flat (sq_cs71_s00260_c109) but the wwise tree
    # nests scene/cut as two dirs: .../sq_cs71_s00260/c109/sq_cs71_s00260_c109_sound.
    cands = ca.candidate_sound_cores("sq_cs71_s00260_c109")
    assert f"{ROOT}/cs71/sq_cs71_s00260_c109/sq_cs71_s00260_c109_sound" in cands
    assert f"{ROOT}/cs71/sq_cs71_s00260/c109/sq_cs71_s00260_c109_sound" in cands


def test_candidate_sound_cores_unparseable_scene():
    assert ca.candidate_sound_cores("not_a_scene") == []


# ------------------------------------------------ pure: extract voice tracks

def _blob(*strings):
    """Join virtual-path strings the way a core stores them: each preceded by a
    4-byte little-endian length prefix (first byte often printable, rest NUL)."""
    out = b""
    for s in strings:
        out += len(s).to_bytes(4, "little") + s.encode("latin1")
    return out


def test_english_voice_tracks_extracts_and_filters():
    en = f"{ROOT}/cs04/sq_cs04_s01650/wav/english/windows/sq_cs04_s01650_voice_track.english"
    fr = f"{ROOT}/cs04/sq_cs04_s01650/wav/french/windows/sq_cs04_s01650_voice_track.french"
    mande = f"{ROOT}/cs04/sq_cs04_s01650/wav/windows/sq_cs04_s01650_m_and_e_track"
    sfx = f"{ROOT}/cs04/sq_cs04_s01650/wav/windows/sq_cs04_s01650_sfx_igr_track"
    tracks = ca.english_voice_tracks(_blob(mande, sfx, en, fr))
    assert tracks == [en]  # only the english voice track; m_and_e/sfx/french dropped


def test_english_voice_tracks_truncates_trailing_junk():
    # The byte after ".english" is the next field's length prefix; if printable it
    # glues onto the run and must be trimmed exactly at ".english".
    en = f"{ROOT}/cs50/sq_cs50_s01010/wav/english/windows/sq_cs50_s01010_voice_dhm_track.english"
    blob = len(en).to_bytes(4, "little") + en.encode() + b"'" + b"\x00\x00\x00next"
    assert ca.english_voice_tracks(blob) == [en]


def test_english_voice_tracks_multiple_characters():
    base = f"{ROOT}/cs00/sq_cs00_s00400/wav/english/windows/sq_cs00_s00400"
    sam = f"{base}_voice_track_sam.english"
    igor = f"{base}_voice_track_igor.english"
    tracks = ca.english_voice_tracks(_blob(sam, igor))
    assert set(tracks) == {sam, igor}
    assert len(tracks) == 2


def test_english_voice_tracks_dedupes_preserving_order():
    en = f"{ROOT}/cs04/sq_cs04_s01650/wav/english/windows/sq_cs04_s01650_voice_track.english"
    assert ca.english_voice_tracks(_blob(en, en)) == [en]


# ----------------------------------------------------- resolve_scene (fakes)

def _fake_index(cores: dict[str, bytes], existing_streams: set[str]):
    """cores: {sound_core_vpath: bytes}; existing_streams: set of full paths present.
    Returns (read_core, path_exists) callables over an in-memory index."""
    present = set(existing_streams) | {c + ".core" for c in cores}

    def read_core(vpath):
        return cores[vpath]

    def path_exists(full_path):
        return full_path in present

    return read_core, path_exists


def test_resolve_scene_resolved():
    core = f"{ROOT}/cs04/sq_cs04_s01650/sq_cs04_s01650_sound"
    en = f"{ROOT}/cs04/sq_cs04_s01650/wav/english/windows/sq_cs04_s01650_voice_track.english"
    read_core, path_exists = _fake_index({core: _blob(en)}, {en + ".core.stream"})
    res = ca.resolve_scene("sq_cs04_s01650", read_core, path_exists)
    assert res.status == "resolved"
    assert res.voice_tracks == [en + ".core.stream"]


def test_resolve_scene_no_sound_core():
    read_core, path_exists = _fake_index({}, set())
    res = ca.resolve_scene("sq_cs04_s01650", read_core, path_exists)
    assert res.status == "no_sound_core"
    assert res.voice_tracks == []


def test_resolve_scene_no_voice_track():
    core = f"{ROOT}/cs09/sq_cs09_s00030/sq_cs09_s00030_sound"
    mande = f"{ROOT}/cs09/sq_cs09_s00030/wav/windows/sq_cs09_s00030_m_and_e_track"
    read_core, path_exists = _fake_index({core: _blob(mande)}, set())
    res = ca.resolve_scene("sq_cs09_s00030", read_core, path_exists)
    assert res.status == "no_voice_track"


def test_resolve_scene_no_stream_when_track_named_but_absent():
    core = f"{ROOT}/cs04/sq_cs04_s01650/sq_cs04_s01650_sound"
    en = f"{ROOT}/cs04/sq_cs04_s01650/wav/english/windows/sq_cs04_s01650_voice_track.english"
    read_core, path_exists = _fake_index({core: _blob(en)}, set())  # stream NOT present
    res = ca.resolve_scene("sq_cs04_s01650", read_core, path_exists)
    assert res.status == "no_stream"
    assert res.voice_tracks == []


def test_subcut_core_index_groups_per_cut_cores_by_base_scene():
    c101 = f"{ROOT}/cs71/sq_cs71_s00270/c101/sq_cs71_s00270_c101_sound"
    c102 = f"{ROOT}/cs71/sq_cs71_s00270/c102/sq_cs71_s00270_c102_sound"
    listing = [
        c101, c102,
        f"{ROOT}/cs71/sq_cs71_s00270/c101/animations/sqcs71s00270c101_shot001",  # noise
        f"{ROOT}/cs04/sq_cs04_s01650/sq_cs04_s01650_sound",  # flat core, not a sub-cut
    ]
    index = ca.subcut_core_index(listing)
    assert index["sq_cs71_s00270"] == [c101, c102]
    assert "sq_cs04_s01650" not in index  # flat (single-dir) cores are not indexed here


def test_resolve_scene_aggregates_extra_candidate_cores():
    c1 = f"{ROOT}/cs71/sq_cs71_s00270/c101/sq_cs71_s00270_c101_sound"
    c2 = f"{ROOT}/cs71/sq_cs71_s00270/c102/sq_cs71_s00270_c102_sound"
    en1 = f"{ROOT}/cs71/sq_cs71_s00270/c101/wav/english/windows/sq_cs71_s00270_c101_voice_track.english"
    en2 = f"{ROOT}/cs71/sq_cs71_s00270/c102/wav/english/windows/sq_cs71_s00270_c102_voice_track.english"
    read_core, path_exists = _fake_index(
        {c1: _blob(en1), c2: _blob(en2)}, {en1 + ".core.stream", en2 + ".core.stream"})
    res = ca.resolve_scene("sq_cs71_s00270", read_core, path_exists, extra_candidates=[c1, c2])
    assert res.status == "resolved"
    assert res.voice_tracks == [en1 + ".core.stream", en2 + ".core.stream"]


def test_resolve_scene_falls_through_to_nested_subcut():
    nested = f"{ROOT}/cs71/sq_cs71_s00260/c109/sq_cs71_s00260_c109_sound"
    en = f"{ROOT}/cs71/sq_cs71_s00260/c109/wav/english/windows/sq_cs71_s00260_c109_voice_track.english"
    read_core, path_exists = _fake_index({nested: _blob(en)}, {en + ".core.stream"})
    res = ca.resolve_scene("sq_cs71_s00260_c109", read_core, path_exists)
    assert res.status == "resolved"
    assert res.voice_tracks == [en + ".core.stream"]


# --------------------------------------------------------------- csv writer

def test_write_tracks_csv_one_row_per_track(tmp_path):
    s1 = ca.SceneAudio("sq_cs00_s00400", "resolved", ["a.core.stream", "b.core.stream"])
    s2 = ca.SceneAudio("sq_cs11_s00100", "no_sound_core", [])
    out = tmp_path / "cutscene_tracks.csv"
    ca.write_tracks_csv([s1, s2], str(out))

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["scene"] for r in rows] == ["sq_cs00_s00400", "sq_cs00_s00400", "sq_cs11_s00100"]
    assert rows[0]["track_index"] == "0" and rows[0]["voice_track_stream"] == "a.core.stream"
    assert rows[1]["track_index"] == "1" and rows[1]["voice_track_stream"] == "b.core.stream"
    # unresolved scene still emits exactly one row, with empty stream + its status
    assert rows[2]["status"] == "no_sound_core"
    assert rows[2]["voice_track_stream"] == ""


# ------------------------------------------------- integration (real install)

PROVEN_STREAM = (
    "ds/sounds/wwise_cinematics_sound_resource/cs04/sq_cs04_s01650/"
    "wav/english/windows/sq_cs04_s01650_voice_track.english.core.stream"
)


def test_resolve_proven_cutscene_scene_against_install(require_install):
    from deciwaves.engine.pack.bin_index import PackIndex

    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    read_core, path_exists = ca.packindex_accessors(idx)
    res = ca.resolve_scene("sq_cs04_s01650", read_core, path_exists)
    assert res.status == "resolved"
    assert PROVEN_STREAM in res.voice_tracks
