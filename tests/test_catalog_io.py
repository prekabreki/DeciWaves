"""Unit tests for the game-free catalog CSV I/O helpers in catalog_io.py."""

import csv

import pytest

from deciwaves.engine.catalog_io import (
    CsvFormatError, read_csv_rows, read_line_ids,
)


def test_read_csv_rows_no_bom(tmp_path):
    """A plain (no-BOM) CSV round-trips correctly."""
    p = tmp_path / "test.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["a", "b"])
        w.writeheader()
        w.writerow({"a": "1", "b": "2"})
    rows = read_csv_rows(str(p))
    assert rows == [{"a": "1", "b": "2"}]
    assert list(rows[0]) == ["a", "b"]


def test_read_csv_rows_bom_stripped_from_header(tmp_path):
    """A UTF-8 BOM in the file must be stripped so the first column key is
    clean, not ``\ufeffline_id``."""
    p = tmp_path / "test-bom.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "col"])
        w.writeheader()
        w.writerow({"line_id": "abc", "col": "x"})
    rows = read_csv_rows(str(p))
    assert list(rows[0])[0] == "line_id"
    assert rows[0]["line_id"] == "abc"


def test_read_csv_rows_bom_with_required(tmp_path):
    """A BOM-prefixed CSV with required= validates correctly against the
    clean header (not the BOM-fused one)."""
    p = tmp_path / "test-bom-required.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "col"])
        w.writeheader()
        w.writerow({"line_id": "abc", "col": "x"})
    rows = read_csv_rows(str(p), required=["line_id", "col"])
    assert rows[0]["line_id"] == "abc"
    assert rows[0]["col"] == "x"


def test_read_csv_rows_required_missing_column(tmp_path):
    """required= raises CsvFormatError listing the missing column and header."""
    p = tmp_path / "test-missing.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["a", "b"])
        w.writeheader()
        w.writerow({"a": "1", "b": "2"})
    with pytest.raises(CsvFormatError) as exc:
        read_csv_rows(str(p), required=["a", "c"])
    msg = str(exc.value)
    assert "c" in msg
    assert "a, b" in msg or "'a', 'b'" in msg
    assert str(p) in msg


def test_read_csv_rows_required_no_missing_column_passes(tmp_path):
    """All required columns present -> no error, rows returned."""
    p = tmp_path / "test-ok.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["a", "b", "c"])
        w.writeheader()
        w.writerow({"a": "1", "b": "2", "c": "3"})
    rows = read_csv_rows(str(p), required=["a", "c"])
    assert rows[0]["a"] == "1"
    assert rows[0]["c"] == "3"


# --- tolerant reads (the GUI's contract) ------------------------------------


def test_read_csv_rows_missing_file_raises_by_default(tmp_path):
    """A CLI stage wants a missing manifest to be a real, diagnosable failure."""
    with pytest.raises(OSError):
        read_csv_rows(str(tmp_path / "nope.csv"))


def test_read_csv_rows_tolerant_returns_empty_for_missing_file(tmp_path):
    """The GUI reads artifacts that legitimately do not exist yet; [] not a crashed panel."""
    assert read_csv_rows(str(tmp_path / "nope.csv"), tolerant=True) == []


def test_read_csv_rows_tolerant_still_raises_on_bad_header(tmp_path):
    """`tolerant` forgives ABSENT, never MALFORMED.

    Regression guard: CsvFormatError subclasses ValueError, so a naive
    `except (OSError, ValueError)` swallows a missing-column error into [] and the
    caller silently renders nothing instead of being told its manifest is wrong.
    """
    p = tmp_path / "bad.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["a", "b"])
        w.writeheader()
        w.writerow({"a": "1", "b": "2"})
    with pytest.raises(CsvFormatError):
        read_csv_rows(str(p), required=["a", "missing_col"], tolerant=True)


# --- read_line_ids ----------------------------------------------------------


def test_read_line_ids_skips_blanks_and_strips(tmp_path):
    p = tmp_path / "ids.txt"
    p.write_text("id_one\n\n  id_two  \n\n", encoding="utf-8")
    assert read_line_ids(str(p)) == ["id_one", "id_two"]


def test_read_line_ids_strips_bom_from_first_id(tmp_path):
    """A BOM must not fuse into the FIRST id, or exactly one row of a dump goes missing."""
    p = tmp_path / "ids.txt"
    p.write_bytes(b"\xef\xbb\xbfid_one\nid_two\n")
    assert read_line_ids(str(p)) == ["id_one", "id_two"]
