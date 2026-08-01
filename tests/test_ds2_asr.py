"""DS2 ASR transcript pass (``games.ds2.asr_run``): resumable, fail-soft,
injected-``transcribe_fn`` orchestration.

Install-free (mirrors the stub harness in tests/test_ds2_extract.py): the whole
WhisperX chain is stubbed via ``transcribe_fn``, so the resume + fail-soft
bookkeeping runs on any machine with no install, no GPU and no ``[asr]`` extra.
"""
import csv
from collections import namedtuple

from deciwaves.games.ds2 import asr_run

_FakeTranscript = namedtuple("_FakeTranscript", "text speech_ratio")

_MANIFEST_COLS = ["line_id", "group_id", "lssr_index", "file_index",
                  "offset", "clip_bytes", "wav"]


def _write_clip_index(out, n):
    out.mkdir(parents=True, exist_ok=True)
    path = out / "clip-index.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_MANIFEST_COLS)
        w.writeheader()
        for i in range(n):
            w.writerow({"line_id": f"g1_{i:04d}", "group_id": 1, "lssr_index": i,
                        "file_index": 15, "offset": i * 100, "clip_bytes": 32,
                        "wav": f"audio/g1_{i:04d}.wav"})
    return asr_run.load_clip_index(path)


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_clean_run_writes_csv_with_header(tmp_path):
    out = tmp_path / "ds2"
    rows = _write_clip_index(out, 3)

    n_ok, n_err = asr_run.run(
        rows, out / "transcripts.csv", out,
        transcribe_fn=lambda w: _FakeTranscript(w, 0.5))

    assert (n_ok, n_err) == (3, 0)
    rows_out = _read_rows(out / "transcripts.csv")
    assert list(rows_out[0].keys()) == asr_run.TRANSCRIPT_COLS
    assert [r["line_id"] for r in rows_out] == ["g1_0000", "g1_0001", "g1_0002"]
    assert rows_out[0]["transcript"].endswith("g1_0000.wav")
    assert rows_out[0]["speech_ratio"] == "0.5"


def test_resumed_run_skips_done_line_ids(tmp_path):
    out = tmp_path / "ds2"
    rows = _write_clip_index(out, 4)
    transcripts = out / "transcripts.csv"

    n_ok, n_err = asr_run.run(
        rows, transcripts, out,
        transcribe_fn=lambda w: _FakeTranscript("done", 0.9))
    assert (n_ok, n_err) == (4, 0)

    # Second run: every line_id is already cached -- nothing transcribed, no
    # re-appended header row corrupting the CSV.
    n_ok2, n_err2 = asr_run.run(
        rows, transcripts, out,
        transcribe_fn=lambda w: _FakeTranscript("again", 1.0))
    assert (n_ok2, n_err2) == (0, 0)

    rows_out = _read_rows(transcripts)
    assert [r["line_id"] for r in rows_out] == ["g1_0000", "g1_0001",
                                                "g1_0002", "g1_0003"]
    assert all(r["transcript"] == "done" for r in rows_out)  # not re-transcribed


def test_raising_clip_is_logged_and_absent_from_csv(tmp_path):
    out = tmp_path / "ds2"
    rows = _write_clip_index(out, 4)
    logs = []

    def transcribe(wav):
        if wav.endswith("g1_0001.wav"):
            raise RuntimeError("boom")
        return _FakeTranscript("ok", 0.7)

    n_ok, n_err = asr_run.run(rows, out / "transcripts.csv", out,
                              transcribe, log=logs.append)

    assert (n_ok, n_err) == (3, 1)
    assert len(logs) == 1
    assert "g1_0001" in logs[0] and "boom" in logs[0]
    rows_out = _read_rows(out / "transcripts.csv")
    assert {r["line_id"] for r in rows_out} == {"g1_0000", "g1_0002", "g1_0003"}


def test_failed_clip_is_retried_on_the_next_run(tmp_path):
    """A raising clip is left OFF the CSV, so resume does not treat it as done --
    it stays pending and is transcribed exactly once once the failure clears."""
    out = tmp_path / "ds2"
    rows = _write_clip_index(out, 2)
    transcripts = out / "transcripts.csv"
    logs = []

    n_ok, n_err = asr_run.run(rows, transcripts, out,
                              lambda w: (_ for _ in ()).throw(RuntimeError("boom")),
                              log=logs.append)
    assert (n_ok, n_err) == (0, 2)
    assert _read_rows(transcripts) == []   # nothing poisoned by the failures

    n_ok, n_err = asr_run.run(rows, transcripts, out,
                              transcribe_fn=lambda w: _FakeTranscript("ok", 0.5))
    assert (n_ok, n_err) == (2, 0)
    rows_out = _read_rows(transcripts)
    assert [r["line_id"] for r in rows_out] == ["g1_0000", "g1_0001"]
    assert all(r["transcript"] == "ok" for r in rows_out)
