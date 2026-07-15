"""Per-clip fail-soft around dsar.read in the clip-index builder: a clip whose
archive read raises ValueError (bad offset/length -- see test_dsar_archive.py)
must be logged and skipped, not abort the whole index."""
import csv

from deciwaves.engine.pack.fw_locators import Entry
from deciwaves.games.hzd.clip_index import ARCHIVE, COLUMNS, build_clip_index


class FakeDsar:
    """Minimal stand-in for a DsarArchive: raises ValueError for offsets in
    `fail_offsets`, else returns `header_len` zero bytes (no RIFF/fact chunk,
    so fact_sample_count -> None -> b=0; only the read-failure path matters here)."""

    def __init__(self, fail_offsets):
        self.fail_offsets = set(fail_offsets)
        self.calls = []

    def read(self, offset, length):
        self.calls.append(offset)
        if offset in self.fail_offsets:
            raise ValueError(f"no chunk contains offset {offset} in fake.core")
        return b"\x00" * length


def _entries(offsets_lengths):
    return [Entry(ARCHIVE, i, off, length)
            for i, (off, length) in enumerate(offsets_lengths)]


def test_build_clip_index_skips_bad_clip_and_continues(tmp_path):
    entries = _entries([(0, 100), (200, 100), (400, 100)])
    dsar = FakeDsar(fail_offsets={200})    # middle clip's read raises
    out = tmp_path / "clip-index.csv"
    errors = tmp_path / "clip-index-errors.log"

    skipped = build_clip_index(dsar, entries, str(out), str(errors))

    assert skipped == 1
    # all three clips attempted -- the loop did not abort after the failure
    assert dsar.calls == [0, 200, 400]
    rows = list(csv.reader(open(out, newline="")))
    assert rows[0] == COLUMNS
    written_rows = [int(r[0]) for r in rows[1:]]
    assert written_rows == [0, 2]              # clip_row 1 (offset 200) absent
    err_text = errors.read_text(encoding="utf-8")
    assert "200" in err_text                    # the bad clip's row index is logged
    assert "no chunk contains offset 200" in err_text


def test_build_clip_index_no_failures_no_skips(tmp_path):
    entries = _entries([(0, 100), (100, 100)])
    dsar = FakeDsar(fail_offsets=set())
    out = tmp_path / "clip-index.csv"
    errors = tmp_path / "clip-index-errors.log"

    skipped = build_clip_index(dsar, entries, str(out), str(errors))

    assert skipped == 0
    rows = list(csv.reader(open(out, newline="")))
    assert len(rows) == 3   # header + 2 clips
