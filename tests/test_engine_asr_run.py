import csv
from pathlib import Path

from deciwaves.engine import asr_run


class FakeTranscript:
    def __init__(self, text, speech_ratio=0.9):
        self.text = text
        self.speech_ratio = speech_ratio


def _write_clip_index(rows, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "wav"])
        w.writeheader()
        w.writerows(rows)


def test_clean_run_writes_csv_with_header(tmp_path):
    out = tmp_path / "test"
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"}],
        out / "clips.csv",
    )
    rows = asr_run.load_clip_index(out / "clips.csv")
    transcripts = out / "transcripts.csv"
    n_ok, n_err = asr_run.run(
        rows, transcripts, out,
        transcribe_fn=lambda w: FakeTranscript(f"text {Path(w).name}"))

    assert (n_ok, n_err) == (2, 0)
    got = list(csv.DictReader(open(transcripts, encoding="utf-8")))
    assert list(got[0].keys()) == asr_run.TRANSCRIPT_COLS
    assert {r["line_id"]: r["transcript"] for r in got} == {
        "g1_0": "text a.wav", "g1_1": "text b.wav"}


def test_resumed_run_skips_done_line_ids(tmp_path):
    out = tmp_path / "test"
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"}],
        out / "clips.csv",
    )
    rows = asr_run.load_clip_index(out / "clips.csv")
    transcripts = out / "transcripts.csv"

    asr_run.run(rows[:1], transcripts, out,
                transcribe_fn=lambda w: FakeTranscript("first"),
                log=lambda m: None)

    calls = []
    def spy(w):
        calls.append(w)
        return FakeTranscript("second")

    n_ok, n_err = asr_run.run(rows, transcripts, out,
                               transcribe_fn=spy, log=lambda m: None)
    assert (n_ok, n_err) == (1, 0)
    assert len(calls) == 1


def test_raising_clip_is_logged_and_absent_from_csv(tmp_path):
    out = tmp_path / "test"
    _write_clip_index(
        [{"line_id": "g1_0", "wav": "audio/a.wav"},
         {"line_id": "g1_1", "wav": "audio/b.wav"},
         {"line_id": "g1_2", "wav": "audio/c.wav"}],
        out / "clips.csv",
    )
    rows = asr_run.load_clip_index(out / "clips.csv")
    transcripts = out / "transcripts.csv"
    logged = []

    def flaky(w):
        if Path(w).name == "b.wav":
            raise RuntimeError("decode boom")
        return FakeTranscript("ok")

    n_ok, n_err = asr_run.run(rows, transcripts, out,
                               transcribe_fn=flaky, log=logged.append)
    assert (n_ok, n_err) == (2, 1)
    assert any("g1_1" in m for m in logged)
    ids = [r["line_id"] for r in csv.DictReader(open(transcripts, encoding="utf-8"))]
    assert ids == ["g1_0", "g1_2"]


def test_read_done_ids_empty_when_missing(tmp_path):
    assert asr_run.read_done_ids(tmp_path / "nope.csv") == set()


def test_read_done_ids_parses_bom_prefixed_csv(tmp_path):
    p = tmp_path / "t.csv"
    p.write_bytes(
        b"\xef\xbb\xbf" + b"line_id,transcript,speech_ratio\ng1_0,hi,0.9\n")
    assert asr_run.read_done_ids(p) == {"g1_0"}


def test_load_clip_index_parses_bom_prefixed_csv(tmp_path):
    p = tmp_path / "clips.csv"
    p.write_bytes(b"\xef\xbb\xbf" + b"line_id,wav\ng1_0,audio/a.wav\ng1_1,audio/b.wav\n")
    rows = asr_run.load_clip_index(p)
    assert [r["line_id"] for r in rows] == ["g1_0", "g1_1"]
    assert rows[0]["wav"] == "audio/a.wav"
