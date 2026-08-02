"""Tests for DS2 ASR-transcript -> gamescript story matcher.

Matches each gamescript line to the clip whose ASR transcript voices it.
Since DS2 has no exact subtitles, the transcript doubles as the subtitle.
"""

import csv

from deciwaves.games.ds2 import story_match


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_clip_matching_transcript_binds_with_speaker_and_index(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
        {"line_id": "c002", "wav": "audio/c002.wav", "group_id": "10", "lssr_index": "1", "region": "l200_aus"},
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c001", "transcript": "we need to find shelter"},
        {"line_id": "c002", "transcript": "the storm is getting closer"},
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need to find shelter.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    # c001 binds to the script line; c002 is unmatched (tier R) since the
    # single script line doesn't voice it
    assert len(rows) == 2
    bound = next(r for r in rows if r["tier"] != "R")
    assert bound["speaker"] == "Sam"
    assert bound["gamescript_index"] == "0"
    assert bound["subtitle"] == "we need to find shelter"
    assert bound["line_id"] == "c001"
    unmatched = next(r for r in rows if r["tier"] == "R")
    assert unmatched["speaker"] == ""
    assert unmatched["line_id"] == "c002"


def test_non_matching_clip_does_not_bind(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c001", "transcript": "something completely unrelated now"},
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need to find shelter.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out),
                           "--accept", "80"])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 1  # unmatched -> tier R row
    assert rows[0]["tier"] == "R"
    assert rows[0]["speaker"] == ""


def test_sentence_split_one_turn_two_clips_binds_both(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
        {"line_id": "c002", "wav": "audio/c002.wav", "group_id": "10", "lssr_index": "1", "region": "l200_aus"},
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c001", "transcript": "look up at the sky above"},
        {"line_id": "c002", "transcript": "the stars are bright tonight"},
    ], ["line_id", "transcript"])
    gamescript.write_text(
        "Sam: Look up at the sky above. The stars are bright tonight.\n",
        encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 2
    speakers = {r["speaker"] for r in rows}
    assert speakers == {"Sam"}
    indices = {int(r["gamescript_index"]) for r in rows}
    assert indices == {0}
    subtitles = sorted(r["subtitle"] for r in rows)
    assert subtitles == ["look up at the sky above", "the stars are bright tonight"]


def test_inner_join_failed_asr_clip_dropped(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
        {"line_id": "c002", "wav": "audio/c002.wav", "group_id": "10", "lssr_index": "1", "region": "l200_aus"},
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c001", "transcript": "this is a test message"},
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: This is a test message.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 1
    assert rows[0]["line_id"] == "c001"


def test_inner_join_middle_gap_binds_correct_text(tmp_path):
    clips = [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
        {"line_id": "c002", "wav": "audio/c002.wav", "group_id": "10", "lssr_index": "1", "region": "l200_aus"},
        {"line_id": "c003", "wav": "audio/c003.wav", "group_id": "10", "lssr_index": "2", "region": "l200_aus"},
    ]
    txs = [
        {"line_id": "c001", "transcript": "we need to find shelter"},
        {"line_id": "c003", "transcript": "the storm is getting closer"},
    ]
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, clips, ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, txs, ["line_id", "transcript"])
    gamescript.write_text(
        "Sam: We need to find shelter. The storm is getting closer.\n",
        encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 2
    line_ids = {r["line_id"] for r in rows}
    assert line_ids == {"c001", "c003"}
    for r in rows:
        if r["line_id"] == "c001":
            assert r["subtitle"] == "we need to find shelter"
        else:
            assert r["subtitle"] == "the storm is getting closer"
    speakers = {r["speaker"] for r in rows}
    assert speakers == {"Sam"}


def test_ds2_stage_splits_on_ellipsis(tmp_path):
    """The DS2 stage must opt into `…` as a sentence terminator (issue #393).

    Guards the CALLER wiring, not the engine: with the engine default the second
    utterance stays glued to the first and its clip is stranded, so a passing
    engine-level test says nothing about whether this stage passes the flag.
    """
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav", "group_id": "10", "lssr_index": "0", "region": "l200_aus"},
        {"line_id": "c002", "wav": "audio/c002.wav", "group_id": "10", "lssr_index": "1", "region": "l200_aus"},
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c001", "transcript": "no one else has taken on the order as of yet"},
        {"line_id": "c002", "transcript": "I hope you'll at least consider it"},
    ], ["line_id", "transcript"])
    gamescript.write_text(
        "Son: No one else has taken on the order as of yet… "
        "I hope you'll at least consider it.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    bound = {r["line_id"] for r in _read_csv(out)}
    assert bound == {"c001", "c002"}, (
        "both utterances should bind once `…` splits the script turn; "
        f"got {bound}")


# ---------------------------------------------------------------------------
# tier-R region ordering (issue #388)
# ---------------------------------------------------------------------------

def _make_clip(line_id, wav, group, lssr, region="l200_aus"):
    return {"line_id": line_id, "wav": wav, "group_id": str(group),
            "lssr_index": str(lssr), "region": region}


def test_unmatched_anchored_line_sorts_adjacent_to_bound_siblings(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        _make_clip("c01", "audio/c01.wav", 10, 0),
        _make_clip("c02", "audio/c02.wav", 10, 1),
        _make_clip("c03", "audio/c03.wav", 10, 2),
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": lid, "transcript": tx}
        for lid, tx in [("c01", "we need shelter"), ("c02", "something unrelated"),
                        ("c03", "storm getting closer")]
    ], ["line_id", "transcript"])
    gamescript.write_text(
        "Sam: We need shelter. Storm getting closer.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 3  # 2 bound + 1 unmatched
    assert rows[0]["line_id"] in ("c01", "c02")
    assert rows[2]["line_id"] == "c03"
    # Anchored unmatched (c02) sits at c01's gamescript_index AND sorts by
    # lssr_index within the group
    for r in rows:
        if r["line_id"] == "c02":
            assert r["tier"] == "R"
            assert r["speaker"] == ""
            assert r["score"] == ""
            assert int(r["gamescript_index"]) == int(
                next(rr["gamescript_index"] for rr in rows if rr["line_id"] == "c01"))
            assert r["quest"] == next(
                rr["quest"] for rr in rows if rr["line_id"] == "c01")
    # lssr order: c01 (0), c02 (1), c03 (2)
    line_ids = [r["line_id"] for r in rows]
    assert line_ids.index("c01") < line_ids.index("c02")
    assert line_ids.index("c02") < line_ids.index("c03")


def test_orphan_group_sorts_after_bound_rows_and_in_region_order(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        _make_clip("bound1", "audio/bound1.wav", 10, 0),
        _make_clip("orphan_a", "audio/orphan_a.wav", 20, 0, "l100_mex"),
        _make_clip("orphan_b", "audio/orphan_b.wav", 30, 0, "l200_aus"),
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": lid, "transcript": tx}
        for lid, tx in [("bound1", "we need to find shelter now"),
                        ("orphan_a", "mexico chatter is very loud"),
                        ("orphan_b", "australia chatter fills the air")]
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need to find shelter now.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 3
    line_ids = [r["line_id"] for r in rows]
    assert line_ids[0] == "bound1"
    assert "orphan_a" in line_ids and "orphan_b" in line_ids
    # l100_mex (rank 0) < l200_aus (rank 1) -> orphan_a before orphan_b
    assert line_ids.index("orphan_a") < line_ids.index("orphan_b")
    for lid in ("orphan_a", "orphan_b"):
        r = next(r for r in rows if r["line_id"] == lid)
        assert r["tier"] == "R"
        assert r["speaker"] == ""
        assert int(r["gamescript_index"]) >= 10_000_000
        assert "(unmatched)" in r["quest"]


def test_unmatched_rows_have_empty_speaker_and_tier_R(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        _make_clip("c01", "audio/c01.wav", 10, 0),
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c01", "transcript": "some chatter about nothing much"},
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need shelter.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 1
    r = rows[0]
    assert r["tier"] == "R"
    assert r["speaker"] == ""
    assert r["score"] == ""
    assert r["subtitle"] == "some chatter about nothing much"
    assert r["transcript"] == "some chatter about nothing much"


def test_bound_row_gamescript_index_is_unchanged(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        _make_clip("c01", "audio/c01.wav", 10, 0),
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": "c01", "transcript": "we need shelter right now"},
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need shelter right now.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 1
    assert rows[0]["gamescript_index"] == "0"  # unchanged from today
    assert rows[0]["tier"] == "1"
    assert rows[0]["speaker"] == "Sam"


def test_root_sorts_last_among_regions(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        _make_clip("o100", "audio/o100.wav", 100, 0, "l100_mex"),
        _make_clip("oRoot", "audio/oRoot.wav", 200, 0, "root"),
        _make_clip("o200", "audio/o200.wav", 300, 0, "l200_aus"),
    ], ["line_id", "wav", "group_id", "lssr_index", "region"])
    _write_csv(transcripts, [
        {"line_id": lid, "transcript": tx}
        for lid, tx in [("o100", "mexico chatter is very loud here"),
                        ("oRoot", "rooty rooty rooty rooty rooty"),
                        ("o200", "australia chatter fills the air")]
    ], ["line_id", "transcript"])
    gamescript.write_text("Sam: We need shelter.\n", encoding="utf-8")

    rc = story_match.main(["--clip-index", str(clip_index),
                           "--transcripts", str(transcripts),
                           "--gamescript", str(gamescript),
                           "--out", str(out)])
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 3  # all unmatched (no transcript matches "We need shelter.")
    unmatched = [r for r in rows if r["tier"] == "R"]
    u_regions = [r["line_id"] for r in sorted(unmatched,
                  key=lambda r: int(r["gamescript_index"]))]
    assert u_regions == ["o100", "o200", "oRoot"]
