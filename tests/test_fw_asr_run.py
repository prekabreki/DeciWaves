import csv
from pathlib import Path

from deciwaves.games.fw import asr_run


class FakeTranscript:
    def __init__(self, text, speech_ratio=0.9):
        self.text = text
        self.speech_ratio = speech_ratio


def _write_clip_index(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
        w.writerows(rows)


def test_roster_default_resolves_to_packaged(monkeypatch):
    from deciwaves.games.fw import asr_run
    prompt = asr_run.load_initial_prompt(None)          # None = packaged default
    assert "Aloy" in prompt


def test_roster_empty_disables_prompt():
    from deciwaves.games.fw import asr_run
    assert asr_run.load_initial_prompt("") is None


def test_load_initial_prompt_extracts_roster_block(tmp_path):
    md = tmp_path / "roster.md"
    md.write_text(
        "# Roster\n\nsome prose\n\n"
        "## WhisperX initial_prompt (proper nouns)\n\n"
        "```\nAloy, Varl, GAIA, HEPHAESTUS\n```\n\n"
        "## Full roster\n\n| count | speaker |\n",
        encoding="utf-8",
    )
    prompt = asr_run.load_initial_prompt(md)
    assert "Aloy" in prompt and "HEPHAESTUS" in prompt
    assert "prose" not in prompt and "Full roster" not in prompt


def test_read_done_ids_empty_when_missing(tmp_path):
    assert asr_run.read_done_ids(tmp_path / "nope.csv") == set()


def test_read_done_ids_reads_existing(tmp_path):
    p = tmp_path / "t.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=asr_run.TRANSCRIPT_COLS)
        w.writeheader()
        w.writerow({"line_id": "g1_0", "transcript": "hi", "speech_ratio": 0.9})
    assert asr_run.read_done_ids(p) == {"g1_0"}


def test_run_transcribes_pending_and_appends(tmp_path):
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"}],
        tmp_path / "clips.csv",
    )
    rows = asr_run.load_clip_index(tmp_path / "clips.csv")
    out = tmp_path / "transcripts.csv"
    n_ok, n_err = asr_run.run(rows, out, tmp_path,
                              transcribe_fn=lambda w: FakeTranscript(f"text {Path(w).name}"),
                              log=lambda m: None)
    assert (n_ok, n_err) == (2, 0)
    got = {r["line_id"]: r["transcript"] for r in csv.DictReader(open(out, encoding="utf-8"))}
    assert got == {"g1_0": "text a.wav", "g1_1": "text b.wav"}


def test_run_resume_skips_done(tmp_path):
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"}],
        tmp_path / "clips.csv",
    )
    rows = asr_run.load_clip_index(tmp_path / "clips.csv")
    out = tmp_path / "transcripts.csv"
    # first pass does g1_0 only (simulate prior partial run via pre-seeded cache)
    asr_run.run(rows[:1], out, tmp_path, transcribe_fn=lambda w: FakeTranscript("first"),
                log=lambda m: None)
    calls = []

    def spy(w):
        calls.append(w)
        return FakeTranscript("second")

    n_ok, n_err = asr_run.run(rows, out, tmp_path, transcribe_fn=spy, log=lambda m: None)
    assert (n_ok, n_err) == (1, 0)            # only the remaining clip
    assert len(calls) == 1                     # g1_0 skipped, not re-transcribed
    ids = [r["line_id"] for r in csv.DictReader(open(out, encoding="utf-8"))]
    assert ids == ["g1_0", "g1_1"]             # appended, no duplicate header/row


def test_select_clips_by_file_index():
    rows = [{"line_id": "a", "file_index": "15"},
            {"line_id": "b", "file_index": "101"},
            {"line_id": "c", "file_index": "101"}]
    assert [r["line_id"] for r in asr_run.select_clips(rows, file_index="101")] == ["b", "c"]


def test_select_clips_no_filter_returns_all():
    rows = [{"line_id": "a", "file_index": "15"}, {"line_id": "b", "file_index": "101"}]
    assert len(asr_run.select_clips(rows)) == 2


def test_select_clips_limit():
    rows = [{"line_id": str(i), "file_index": "15"} for i in range(10)]
    assert len(asr_run.select_clips(rows, limit=3)) == 3


def test_run_fail_soft(tmp_path):
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"},
         {"line_id": "g1_2", "wav": "audio/c.wav"}],
        tmp_path / "clips.csv",
    )
    rows = asr_run.load_clip_index(tmp_path / "clips.csv")
    out = tmp_path / "transcripts.csv"
    logged = []

    def flaky(w):
        if Path(w).name == "b.wav":
            raise RuntimeError("decode boom")
        return FakeTranscript("ok")

    n_ok, n_err = asr_run.run(rows, out, tmp_path, transcribe_fn=flaky, log=logged.append)
    assert (n_ok, n_err) == (2, 1)             # run did not abort on the failure
    assert any("g1_1" in m for m in logged)
    ids = [r["line_id"] for r in csv.DictReader(open(out, encoding="utf-8"))]
    assert ids == ["g1_0", "g1_2"]             # failed clip absent, retryable next run
