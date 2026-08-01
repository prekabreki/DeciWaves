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
        {"line_id": "c001", "wav": "audio/c001.wav"},
        {"line_id": "c002", "wav": "audio/c002.wav"},
    ], ["line_id", "wav"])
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
    assert len(rows) == 1
    assert rows[0]["speaker"] == "Sam"
    assert rows[0]["gamescript_index"] == "0"
    assert rows[0]["subtitle"] == "we need to find shelter"
    assert rows[0]["line_id"] == "c001"


def test_non_matching_clip_does_not_bind(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav"},
    ], ["line_id", "wav"])
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
    assert len(rows) == 0


def test_sentence_split_one_turn_two_clips_binds_both(tmp_path):
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, [
        {"line_id": "c001", "wav": "audio/c001.wav"},
        {"line_id": "c002", "wav": "audio/c002.wav"},
    ], ["line_id", "wav"])
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
        {"line_id": "c001", "wav": "audio/c001.wav"},
        {"line_id": "c002", "wav": "audio/c002.wav"},
    ], ["line_id", "wav"])
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
        {"line_id": "c001", "wav": "audio/c001.wav"},
        {"line_id": "c002", "wav": "audio/c002.wav"},
        {"line_id": "c003", "wav": "audio/c003.wav"},
    ]
    txs = [
        {"line_id": "c001", "transcript": "we need to find shelter"},
        {"line_id": "c003", "transcript": "the storm is getting closer"},
    ]
    clip_index = tmp_path / "clip-index.csv"
    transcripts = tmp_path / "transcripts.csv"
    gamescript = tmp_path / "gamescript.md"
    out = tmp_path / "story-manifest.csv"

    _write_csv(clip_index, clips, ["line_id", "wav"])
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
