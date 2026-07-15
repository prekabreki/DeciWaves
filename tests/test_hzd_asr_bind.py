"""Per-clip fail-soft + incremental checkpointing for the HZD ASR-bind stage (Task 14 /
issue #20): one corrupt clip (Atrac9Error from decode, or ValueError from a hardened
dsar.read -- see test_dsar_archive.py / dsar_archive.py) must be logged and skipped, never
abort the whole (hours-long, GPU) stage; successful transcripts are checkpointed to a sidecar
as they are produced so a crashed/interrupted run can resume."""
import csv

import pytest

from deciwaves.games.hzd import asr_bind
from deciwaves.games.hzd.atrac9 import Atrac9Error


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_fixture(tmp_path, n_clips=3):
    """One story-relevant line, one ambiguous (A,B) bucket of `n_clips` clips all needing
    ASR (1 line vs N>1 clips is "ambiguous" per binding.build_buckets)."""
    catalog = tmp_path / "catalog.csv"
    wem_meta = tmp_path / "wem-metadata.csv"
    clip_index = tmp_path / "clip-index.csv"

    _write_csv(catalog,
               [{"line_id": "L1", "category": "main_quest", "subtitle_en": "Hello there",
                 "speaker_name": "Aloy", "scene": "s1"}],
               ["line_id", "category", "subtitle_en", "speaker_name", "scene"])
    _write_csv(wem_meta,
               [{"line_id": "L1", "a_bytes": "500", "b_samples": "2000"}],
               ["line_id", "a_bytes", "b_samples"])
    _write_csv(clip_index,
               [{"clip_row": str(i), "offset": str(1000 * (i + 1)),
                 "a_bytes": "500", "b_samples": "2000"} for i in range(n_clips)],
               ["clip_row", "offset", "a_bytes", "b_samples"])
    return catalog, wem_meta, clip_index


class FakeDsar:
    """Stands in for FwPackage(...).dsar_for(...): raises ValueError for offsets in
    `fail_offsets` (simulating the hardened dsar_archive.read on a corrupt region),
    else returns dummy "wem" bytes tagged with the offset."""

    def __init__(self, fail_offsets=()):
        self.fail_offsets = set(fail_offsets)
        self.calls = []

    def read(self, offset, length):
        self.calls.append(offset)
        if offset in self.fail_offsets:
            raise ValueError(f"no chunk contains offset {offset} in fake.core")
        return f"WEM{offset}".encode()


class FakePackage:
    """Stand-in for FwPackage: callable class instance so `FwPackage(path)` returns self,
    same lazily-cached-dsar shape asr_bind.py expects (`.dsar_for(ARCHIVE)`)."""

    def __init__(self, dsar):
        self._dsar = dsar

    def __call__(self, path):
        return self

    def dsar_for(self, archive):
        return self._dsar


class FakeTranscript:
    def __init__(self, text):
        self.text = text


def _patch_asr_stack(monkeypatch, dsar, decode_fail_marker=None, transcribe_fn=None):
    """Wire fakes so main() never touches VGAudioCli/WhisperX/a real archive."""
    import deciwaves.games.hzd.asr as asr_mod

    monkeypatch.setattr(asr_bind, "FwPackage", FakePackage(dsar))
    monkeypatch.setattr(asr_mod, "load_model", lambda *a, **k: object())

    def fake_decode(wem_bytes, wav_path):
        if decode_fail_marker is not None and decode_fail_marker in wem_bytes:
            raise Atrac9Error("VGAudioCli failed: bad atrac9 header")
        with open(wav_path, "wb") as f:
            f.write(b"RIFF....WAVEfmt ")

    monkeypatch.setattr(asr_bind, "decode_wem_to_wav", fake_decode)

    if transcribe_fn is None:
        def transcribe_fn(wav_path, model, **kw):
            return FakeTranscript("ok")

    monkeypatch.setattr(asr_mod, "transcribe", transcribe_fn)


def _argv(tmp_path, catalog, wem_meta, clip_index, **extra):
    argv = ["--package", "FAKE_PKG",
            "--clip-index", str(clip_index),
            "--wem-metadata", str(wem_meta),
            "--catalog", str(catalog),
            "--out", str(tmp_path / "asr-manifest.csv"),
            "--errors", str(tmp_path / "asr-errors.log"),
            "--transcripts-out", str(tmp_path / "asr-transcripts.csv")]
    for k, v in extra.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return argv


def _manifest_clip_rows(tmp_path):
    with open(tmp_path / "asr-manifest.csv", newline="", encoding="utf-8") as f:
        return [r["clip_row"] for r in csv.DictReader(f) if r["clip_row"]]


def test_decode_error_among_n_clips_is_fail_soft(tmp_path, monkeypatch):
    """One clip's decode raises Atrac9Error -> run completes, N-1 transcribed, the
    errors file has the failure, and the manifest excludes the failed clip."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar, decode_fail_marker=b"2000")  # clip_row 1 (offset 2000)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    assert rc == 0
    assert dsar.calls == [1000, 2000, 3000]           # all three clips attempted
    err_text = (tmp_path / "asr-errors.log").read_text(encoding="utf-8")
    assert "1\t" in err_text and "bad atrac9 header" in err_text
    sidecar_rows = list(csv.DictReader(open(tmp_path / "asr-transcripts.csv", encoding="utf-8")))
    assert {r["clip_row"] for r in sidecar_rows} == {"0", "2"}
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "2"}   # clip_row 1 excluded


def test_archive_read_valueerror_among_n_clips_is_fail_soft(tmp_path, monkeypatch):
    """A hardened dsar.read raising ValueError (corrupt/out-of-range archive region,
    see games/hzd/asr_bind.py review note) must be caught the same as Atrac9Error."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    dsar = FakeDsar(fail_offsets={2000})              # clip_row 1's archive read is corrupt
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    assert rc == 0
    err_text = (tmp_path / "asr-errors.log").read_text(encoding="utf-8")
    assert "1\t" in err_text and "no chunk contains offset 2000" in err_text
    sidecar_rows = list(csv.DictReader(open(tmp_path / "asr-transcripts.csv", encoding="utf-8")))
    assert {r["clip_row"] for r in sidecar_rows} == {"0", "2"}
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "2"}


def test_sidecar_checkpoints_incrementally_and_survives_an_abort(tmp_path, monkeypatch):
    """An unexpected (uncaught) error mid-run must still propagate -- we only fail-soft
    known decode/archive errors, never blanket-except the loop -- but the sidecar must
    already hold every clip transcribed before the crash (write-through per clip)."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=4)
    dsar = FakeDsar()

    class _BoomError(Exception):
        pass

    calls = []

    def flaky_transcribe(wav_path, model, **kw):
        calls.append(wav_path)
        if len(calls) == 3:            # 3rd clip processed: simulate an unrelated crash
            raise _BoomError("totally unexpected bug, not decode-related")
        return FakeTranscript("ok")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=flaky_transcribe)

    with pytest.raises(_BoomError):
        asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    # the 2 clips transcribed before the crash are durably checkpointed on disk
    sidecar_rows = list(csv.DictReader(open(tmp_path / "asr-transcripts.csv", encoding="utf-8")))
    assert {r["clip_row"] for r in sidecar_rows} == {"0", "1"}
    assert len(calls) == 3               # the 4th clip was never attempted


def test_resume_with_transcripts_sidecar_skips_already_done_clips(tmp_path, monkeypatch):
    """The documented resume recipe: rerun with --transcripts <sidecar> (+ --package) after
    a crash/interrupt -- already-checkpointed clips are skipped, only the remainder is
    (re)transcribed, and the sidecar ends up holding all of them."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    sidecar = tmp_path / "asr-transcripts.csv"
    # pre-seed the sidecar as if a prior run checkpointed clip_row 0 and 2 before crashing
    _write_csv(sidecar,
               [{"clip_row": "0", "transcript": "prior ok"},
                {"clip_row": "2", "transcript": "prior ok"}],
               asr_bind.TRANSCRIPTS_COLS)

    dsar = FakeDsar()
    calls = []

    def spy_transcribe(wav_path, model, **kw):
        calls.append(wav_path)
        return FakeTranscript("new")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=spy_transcribe)

    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(sidecar))
    rc = asr_bind.main(argv)

    assert rc == 0
    assert dsar.calls == [2000]                        # only clip_row 1 (offset 2000) redone
    assert len(calls) == 1
    rows = list(csv.DictReader(open(sidecar, encoding="utf-8")))
    assert {r["clip_row"] for r in rows} == {"0", "1", "2"}   # old rows kept, new one appended
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "1", "2"}
