"""Per-clip fail-soft around dsar.read in the clip-index builder: a clip whose
archive read raises ValueError (bad offset/length -- see test_dsar_archive.py)
must be logged and skipped, not abort the whole index."""
import csv

from deciwaves.engine.pack.hzd_locators import Entry
from deciwaves.games.hzd import clip_index as clip_index_mod
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


def test_build_clip_index_parallel_output_identical_to_serial(tmp_path):
    """--jobs>1 reads/parses clip headers concurrently but must write a CSV
    byte-identical to the serial build (rows stay in clip-row order) and the same
    skip count (issue #41)."""
    import struct
    import time

    class JitterDsar:
        def __init__(self, fail_offsets):
            self.fail_offsets = set(fail_offsets)

        def read(self, offset, length):
            time.sleep((offset // 100 % 4) * 0.001)   # completion order != input order
            if offset in self.fail_offsets:
                raise ValueError(f"no chunk contains offset {offset} in fake.core")
            # a valid RIFF with a fact chunk so a_bytes/b_samples are non-trivial
            fact = b"fact" + struct.pack("<II", 4, offset + 7)
            body = b"WAVEfmt " + struct.pack("<I", 16) + b"\x00" * 16 + fact
            return (b"RIFF" + struct.pack("<I", len(body)) + body)[:length]

    entries = _entries([(i * 100, 100) for i in range(30)])
    fails = {500, 1300, 2100}

    def build(jobs, tag):
        out = tmp_path / f"idx_{tag}.csv"
        err = tmp_path / f"err_{tag}.log"
        skipped = build_clip_index(JitterDsar(fails), entries, str(out), str(err), jobs=jobs)
        return skipped, out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")

    s_skip, s_csv, s_err = build(1, "serial")
    p_skip, p_csv, p_err = build(8, "parallel")

    assert p_skip == s_skip == 3
    assert p_csv == s_csv, "parallel CSV must be byte-identical to serial"
    # error lines: same set (order may differ across the pool) and same count
    assert sorted(p_err.splitlines()) == sorted(s_err.splitlines())


def test_build_clip_index_no_failures_no_skips(tmp_path):
    entries = _entries([(0, 100), (100, 100)])
    dsar = FakeDsar(fail_offsets=set())
    out = tmp_path / "clip-index.csv"
    errors = tmp_path / "clip-index-errors.log"

    skipped = build_clip_index(dsar, entries, str(out), str(errors))

    assert skipped == 0
    rows = list(csv.reader(open(out, newline="")))
    assert len(rows) == 3   # header + 2 clips


# ---------------------------------------------------------------------------
# main(): a bad --package (issue #49, mirrors #34's hzd_catalog check) must fail
# actionably, not with a raw FileNotFoundError traceback from hzd_locators.
# ---------------------------------------------------------------------------

def test_clip_index_main_missing_package_fails_actionably(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    bad_package = tmp_path / "install_root"  # exists, but no PackFileLocators.bin
    bad_package.mkdir()

    rc = clip_index_mod.main(["--package", str(bad_package)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "--hzd-package" in captured.out
    assert "PackFileLocators.bin" in captured.out
    assert captured.err == ""  # no traceback
