import csv
import pytest
from deciwaves import data

def test_packaged_keepspans_resolves_and_parses():
    p = data.packaged("ds/cutscene-keepspans.csv")
    assert p.is_file()
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert {"stream_path", "keep_spans", "dropped"} <= set(rows[0])

def test_packaged_fw_roster_has_prompt_block():
    text = data.packaged("fw/character_names.md").read_text(encoding="utf-8")
    assert "```initial_prompt" in text

def test_packaged_missing_raises_with_name():
    with pytest.raises(FileNotFoundError, match="nope/missing.txt"):
        data.packaged("nope/missing.txt")

def test_packaged_ds_file_list_has_sentence_paths():
    lines = data.packaged("ds/data-file-list.txt").read_text(encoding="utf-8").splitlines()
    assert lines
    assert any("localized/sentences" in ln for ln in lines)

def test_packaged_ds_file_list_has_dialogue_and_simpletext_paths():
    """The bundled DS file list carries both the dialogue sentence cores (what
    games.ds.catalog.select_core_paths selects) and the voice simpletext cores
    (what engine.speakers.SpeakerMap's default filter selects), so an
    out-of-box `deciwaves ds` run can derive speaker names live from the
    user's install."""
    lines = data.packaged("ds/data-file-list.txt").read_text(encoding="utf-8").splitlines()
    dialogue = [ln for ln in lines if ln.strip().endswith("/sentences")]
    simpletext = [
        ln for ln in lines if "sentences/voices/" in ln and ln.strip().endswith("/simpletext")
    ]
    assert len(dialogue) == 282
    assert len(simpletext) == 96
    # No overlap between the two shapes, and every line is one or the other.
    assert len(dialogue) + len(simpletext) == len(lines)

def test_packaged_ds_cutscene_tracks_parses_with_expected_header():
    p = data.packaged("ds/cutscene_tracks.csv")
    assert p.is_file()
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert rows
    assert set(rows[0]) == {"scene", "status", "track_index", "voice_track_stream"}
