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
