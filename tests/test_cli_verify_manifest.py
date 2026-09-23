"""TDD for `deciwaves verify-manifest` (issue #407): the deterministic gate between an
externally curated manifest and a render. Every hard-failure branch (rc 1), both report
branches (rc 0), and the missing/empty/no-id-column input errors, on tmp_path CSVs only.
"""
import csv

import pytest

from deciwaves.cli import main as cli_main
from deciwaves.cli.verify_manifest import run_verify_manifest

UUID = "a3f1c2d4-0b9e-4c7a-8d21-5e6f7a8b9c0d_0001_sentence_line"


def _write(path, rows, fields=("line_id", "category", "wav"), bom=False):
    with open(path, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(path)


def _source(tmp_path, n=20, **kw):
    rows = [{"line_id": f"L{i:03d}", "category": "cutscene" if i % 4 else "codec", "wav": f"L{i:03d}.wav"}
            for i in range(n)]
    return rows, _write(tmp_path / "source.csv", rows, **kw)


def _run(capsys, *argv):
    rc = run_verify_manifest(list(argv))
    out, err = capsys.readouterr()
    return rc, out, err


# --- clean pass + the always-on report ----------------------------------------------------

def test_identical_curated_passes_and_reports_full_keep(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 0
    assert "kept 20 / 20 source rows (100.0%)" in out
    assert "FAIL" not in out
    assert out.rstrip().endswith("verify-manifest: ok")


def test_reordered_subset_passes(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", list(reversed(rows[::2])))
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 0
    assert "kept 10 / 20 source rows (50.0%)" in out


def test_bom_on_both_files_is_transparent(tmp_path, capsys):
    """#304: a BOM must not fuse into the first header key and hide the id column."""
    rows, src = _source(tmp_path, bom=True)
    cur = _write(tmp_path / "curated.csv", rows[:5], bom=True)
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 0
    assert "kept 5 / 20" in out


def test_ids_are_whitespace_stripped(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", [{"line_id": f"  {rows[0]['line_id']} "}], fields=("line_id",))
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 0
    assert "kept 1 / 20" in out


# --- hard failure: id not in source --------------------------------------------------------

def test_one_character_corruption_of_a_uuid_fails(tmp_path, capsys):
    """The danger zone: an id differing from a real one by ONE character must fail."""
    src = _write(tmp_path / "source.csv", [{"line_id": UUID}, {"line_id": "other"}])
    corrupt = UUID[:-1] + "E"
    assert corrupt != UUID and len(corrupt) == len(UUID)
    cur = _write(tmp_path / "curated.csv", [{"line_id": "other"}, {"line_id": corrupt}])
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 1
    assert f"FAIL: 1 line_id(s) not in the source: {corrupt} (row 3)" in out
    assert out.rstrip().endswith("verify-manifest: FAILED")


def test_id_comparison_is_case_sensitive(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", [{"line_id": rows[0]["line_id"].lower()}], fields=("line_id",))
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 1
    assert "1 line_id(s) not in the source: l000 (row 2)" in out


def test_unknown_ids_report_count_and_at_most_five_examples(tmp_path, capsys):
    rows, src = _source(tmp_path)
    bogus = [{"line_id": f"X{i}"} for i in range(7)]
    cur = _write(tmp_path / "curated.csv", rows[:2] + bogus, fields=("line_id",))
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 1
    line = next(ln for ln in out.splitlines() if "not in the source" in ln)
    assert line.startswith("FAIL: 7 line_id(s) not in the source: X0 (row 4)")
    assert "X4 (row 8)" in line and "X5" not in line
    assert "kept 2 / 20" in out  # unknown ids never count as kept


def test_blank_id_in_curated_is_an_unknown_id(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", [rows[0], {"line_id": "", "category": "codec"}])
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 1
    assert "1 line_id(s) not in the source: <blank> (row 3)" in out


# --- hard failure: duplicate id -------------------------------------------------------------

def test_duplicate_id_fails(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", [rows[0], rows[1], rows[0], rows[0]])
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 1
    assert "FAIL: 2 duplicate line_id(s) (a line can't play twice): L000 (row 4), L000 (row 5)" in out
    assert "not in the source" not in out


# --- hard failure: missing / empty audio ----------------------------------------------------

def _audio(tmp_path, rows, sizes):
    root = tmp_path / "audio"
    root.mkdir()
    for row, size in zip(rows, sizes):
        if size is not None:
            (root / row["wav"]).write_bytes(b"x" * size)
    return root


def test_present_audio_passes_path_check(tmp_path, capsys):
    rows, src = _source(tmp_path, n=3)
    root = _audio(tmp_path, rows, [10, 10, 10])
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src, "--path-col", "wav", "--path-root", str(root))
    assert rc == 0


def test_missing_and_zero_byte_audio_fail(tmp_path, capsys):
    rows, src = _source(tmp_path, n=4)
    root = _audio(tmp_path, rows, [10, None, 0, 10])
    rows[3] = dict(rows[3], wav="")  # a blank path cell is missing audio, too
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src, "--path-col", "wav", "--path-root", str(root))
    assert rc == 1
    assert "FAIL: 3 missing or empty audio file(s) in wav" in out
    assert "L001.wav (row 3), L002.wav (row 4), <blank> (row 5)" in out


def test_a_directory_is_not_audio(tmp_path, capsys):
    rows, src = _source(tmp_path, n=1)
    root = _audio(tmp_path, rows, [None])
    (root / rows[0]["wav"]).mkdir()
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src, "--path-col", "wav", "--path-root", str(root))
    assert rc == 1
    assert "1 missing or empty audio file(s)" in out


def test_path_check_is_skipped_without_path_col(tmp_path, capsys):
    rows, src = _source(tmp_path)  # no audio on disk at all
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src)
    assert rc == 0
    assert "audio" not in out


def test_every_hard_failure_is_reported_in_one_run(tmp_path, capsys):
    rows, src = _source(tmp_path, n=2)
    root = _audio(tmp_path, rows, [10, 10])
    cur = _write(tmp_path / "curated.csv", [rows[0], rows[0], {"line_id": "nope", "wav": "gone.wav"}])
    rc, out, _ = _run(capsys, cur, "--against", src, "--path-col", "wav", "--path-root", str(root))
    assert rc == 1
    assert sum(ln.startswith("FAIL:") for ln in out.splitlines()) == 3


# --- report: positional buckets over SOURCE order ------------------------------------------

def _bucket_lines(out):
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("bucket ")]


def test_buckets_are_over_source_order_not_curated_order(tmp_path, capsys):
    """The danger zone: an editor that kept everything early and nothing late must show a
    sagging tail. Bucketing the curated rows would read 100% everywhere; reversing the
    curated order must not move the buckets either."""
    rows, src = _source(tmp_path, n=100)
    kept = rows[:30] + rows[45:50]  # buckets 1-3 full, bucket 5 half, the rest empty
    for order in (kept, list(reversed(kept))):
        cur = _write(tmp_path / "curated.csv", order)
        rc, out, _ = _run(capsys, cur, "--against", src)
        assert rc == 0
        assert _bucket_lines(out) == [
            "bucket 1/10: 100.0% (10/10)", "bucket 2/10: 100.0% (10/10)", "bucket 3/10: 100.0% (10/10)",
            "bucket 4/10: 0.0% (0/10)", "bucket 5/10: 50.0% (5/10)", "bucket 6/10: 0.0% (0/10)",
            "bucket 7/10: 0.0% (0/10)", "bucket 8/10: 0.0% (0/10)", "bucket 9/10: 0.0% (0/10)",
            "bucket 10/10: 0.0% (0/10)",
        ]


def test_uneven_buckets_cover_every_source_row(tmp_path, capsys):
    rows, src = _source(tmp_path, n=23)
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src, "--buckets", "4")
    assert rc == 0
    lines = _bucket_lines(out)
    assert len(lines) == 4
    assert sum(int(ln.split("/")[-1].rstrip(")")) for ln in lines) == 23


def test_fewer_source_rows_than_buckets(tmp_path, capsys):
    rows, src = _source(tmp_path, n=3)
    cur = _write(tmp_path / "curated.csv", rows[:1])
    rc, out, _ = _run(capsys, cur, "--against", src, "--buckets", "10")
    assert rc == 0
    assert _bucket_lines(out) == ["bucket 1/3: 100.0% (1/1)", "bucket 2/3: 0.0% (0/1)", "bucket 3/3: 0.0% (0/1)"]


def test_buckets_zero_disables_the_bucket_report(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, _ = _run(capsys, cur, "--against", src, "--buckets", "0")
    assert rc == 0
    assert _bucket_lines(out) == []


def test_negative_buckets_is_a_usage_error(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    with pytest.raises(SystemExit) as exc:
        run_verify_manifest([cur, "--against", src, "--buckets", "-1"])
    assert exc.value.code == 2


# --- report: per-group keep rate ------------------------------------------------------------

def test_group_report_sorted_by_source_count_descending(tmp_path, capsys):
    rows, src = _source(tmp_path)  # 15 cutscene, 5 codec
    kept = [r for r in rows if r["category"] == "codec"] + [r for r in rows if r["category"] == "cutscene"][:3]
    cur = _write(tmp_path / "curated.csv", kept)
    rc, out, _ = _run(capsys, cur, "--against", src, "--group-col", "category")
    assert rc == 0
    lines = out.splitlines()
    i = lines.index("keep-rate by category (source count descending):")
    assert [ln.strip() for ln in lines[i + 1:i + 3]] == ["cutscene: 20.0% (3/15)", "codec: 100.0% (5/5)"]


def test_group_col_absent_from_source_is_a_clean_error(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    rc, out, err = _run(capsys, cur, "--against", src, "--group-col", "scene")
    assert rc == 1
    assert "has no 'scene' column" in err
    assert "Traceback" not in err


# --- input errors: rc 1, one clean line, never a traceback ---------------------------------

@pytest.mark.parametrize("which", ["curated", "source"])
def test_missing_file(tmp_path, capsys, which):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    gone = str(tmp_path / "gone.csv")
    argv = [gone, "--against", src] if which == "curated" else [cur, "--against", gone]
    rc, out, err = _run(capsys, *argv)
    assert rc == 1
    assert err.startswith(f"verify-manifest: error: {which} file not found")
    assert out == ""


@pytest.mark.parametrize("content", ["", "line_id,wav\n"], ids=["zero-bytes", "header-only"])
@pytest.mark.parametrize("which", ["curated", "source"])
def test_empty_file(tmp_path, capsys, which, content):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    empty = tmp_path / "empty.csv"
    empty.write_text(content, encoding="utf-8")
    argv = [str(empty), "--against", src] if which == "curated" else [cur, "--against", str(empty)]
    rc, out, err = _run(capsys, *argv)
    assert rc == 1
    assert err.startswith(f"verify-manifest: error: {which} file")
    assert "empty" in err or "no rows" in err


@pytest.mark.parametrize("which", ["curated", "source"])
def test_file_without_id_column(tmp_path, capsys, which):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows)
    bad = _write(tmp_path / "bad.csv", [{"id": "L000"}], fields=("id",))
    argv = [bad, "--against", src] if which == "curated" else [cur, "--against", bad]
    rc, _, err = _run(capsys, *argv)
    assert rc == 1
    assert f"{which} file" in err and "has no 'line_id' column (header has: id)" in err


def test_custom_id_col(tmp_path, capsys):
    src = _write(tmp_path / "source.csv", [{"clip": "a"}, {"clip": "b"}], fields=("clip",))
    cur = _write(tmp_path / "curated.csv", [{"clip": "b"}, {"clip": "c"}], fields=("clip",))
    rc, out, _ = _run(capsys, cur, "--against", src, "--id-col", "clip")
    assert rc == 1
    assert "1 clip(s) not in the source: c (row 3)" in out


def test_path_col_absent_from_curated_is_a_clean_error(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows, fields=("line_id",))
    rc, _, err = _run(capsys, cur, "--against", src, "--path-col", "stream_path")
    assert rc == 1
    assert "curated file" in err and "has no 'stream_path' column" in err


def test_non_utf8_file_is_a_clean_error(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = tmp_path / "curated.csv"
    cur.write_bytes("line_id\nL\xe9\n".encode("cp1252"))
    rc, _, err = _run(capsys, str(cur), "--against", src)
    assert rc == 1
    assert err.startswith("verify-manifest: error: could not read curated file")


# --- dispatch through `deciwaves` -----------------------------------------------------------

def test_dispatched_from_main(tmp_path, capsys):
    rows, src = _source(tmp_path)
    cur = _write(tmp_path / "curated.csv", rows[:4])
    assert cli_main.main(["verify-manifest", cur, "--against", src]) == 0
    assert "kept 4 / 20" in capsys.readouterr().out
    bad = _write(tmp_path / "bad.csv", [rows[0], rows[0]])
    assert cli_main.main(["verify-manifest", bad, "--against", src]) == 1


def test_main_returns_2_on_usage_error(capsys):
    assert cli_main.main(["verify-manifest"]) == 2  # no curated, no --against
