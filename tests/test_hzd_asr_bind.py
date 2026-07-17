"""Per-clip fail-soft + incremental checkpointing for the HZD ASR-bind stage (Task 14 /
issue #20): one corrupt clip (Atrac9Error from decode, or ValueError from a hardened
dsar.read -- see test_dsar_archive.py / dsar_archive.py) must be logged and skipped, never
abort the whole (hours-long, GPU) stage; successful transcripts are checkpointed to a sidecar
as they are produced so a crashed/interrupted run can resume."""
import csv
import os

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
    """Stands in for HzdPackage(...).dsar_for(...): raises ValueError for offsets in
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
    """Stand-in for HzdPackage: callable class instance so `HzdPackage(path)` returns self,
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
    import deciwaves.engine.asr as asr_mod

    monkeypatch.setattr(asr_bind, "HzdPackage", FakePackage(dsar))
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


def _write_multi_bucket_fixture(tmp_path, n_buckets):
    """`n_buckets` independent ambiguous buckets, each with 2 candidate lines sharing one
    (a_bytes, b_samples) key but exactly 1 clip -- ambiguous because len(lines) > 1 (see
    binding.relevant_buckets' skip condition), and exactly 1 clip per bucket so each
    consumed bucket advances the --sample-cap loop's `len(want)` by exactly 1. That makes
    the cap's bucket-vs-clip-count boundary arithmetic exact: N buckets <-> N clips, so a
    --sample-cap of N consumes exactly N buckets, never overshooting mid-bucket."""
    catalog = tmp_path / "catalog.csv"
    wem_meta = tmp_path / "wem-metadata.csv"
    clip_index = tmp_path / "clip-index.csv"

    catalog_rows, wem_rows, clip_rows = [], [], []
    for i in range(n_buckets):
        a_bytes = 500 + i
        for suffix in ("a", "b"):
            line_id = f"L{i}{suffix}"
            catalog_rows.append({"line_id": line_id, "category": "main_quest",
                                  "subtitle_en": f"Line {i}{suffix}",
                                  "speaker_name": "Aloy", "scene": "s1"})
            wem_rows.append({"line_id": line_id, "a_bytes": str(a_bytes), "b_samples": "2000"})
        clip_rows.append({"clip_row": str(i), "offset": str(1000 * (i + 1)),
                           "a_bytes": str(a_bytes), "b_samples": "2000"})

    _write_csv(catalog, catalog_rows,
               ["line_id", "category", "subtitle_en", "speaker_name", "scene"])
    _write_csv(wem_meta, wem_rows, ["line_id", "a_bytes", "b_samples"])
    _write_csv(clip_index, clip_rows, ["clip_row", "offset", "a_bytes", "b_samples"])
    return catalog, wem_meta, clip_index


def _fake_package_dir(tmp_path):
    """A real directory shaped like a valid HZDR package dir (has
    PackFileLocators.bin), so it passes hzd_package_error while HzdPackage itself
    stays fully mocked (see FakePackage -- it ignores the path value entirely).
    Reused across tests via a fixed subdirectory name so repeated calls are
    idempotent."""
    pkg = tmp_path / "fake_package"
    pkg.mkdir(exist_ok=True)
    locators = pkg / "PackFileLocators.bin"
    if not locators.is_file():
        locators.write_bytes(b"x")
    return str(pkg)


def _argv(tmp_path, catalog, wem_meta, clip_index, **extra):
    argv = ["--package", _fake_package_dir(tmp_path),
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


def test_torn_final_row_in_sidecar_is_dropped_and_warned_and_retranscribed(tmp_path, monkeypatch, capsys):
    """A sidecar whose last row was torn by a crash mid-write (last byte isn't a newline)
    must have exactly that row dropped on load, a kept/dropped warning printed to stderr,
    and (since the drop makes clip_row 2 look un-checkpointed) a resume re-transcribes it."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    sidecar = tmp_path / "asr-transcripts.csv"
    # two intact rows + a torn final row (no trailing newline, truncated mid-value) --
    # exactly the shape described in the review finding.
    with open(sidecar, "w", newline="", encoding="utf-8") as f:
        f.write("clip_row,transcript\r\n")
        f.write("0,prior ok\r\n")
        f.write("1,prior ok\r\n")
        f.write("2,this is a partial tran")   # no trailing newline: torn

    dsar = FakeDsar()
    calls = []

    def spy_transcribe(wav_path, model, **kw):
        calls.append(wav_path)
        return FakeTranscript("new")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=spy_transcribe)

    # write the fresh sidecar to a different path so this test only exercises the
    # reader's drop behavior, not the (separate, out-of-scope) question of appending
    # onto a physically torn file.
    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(sidecar),
                 transcripts_out=str(tmp_path / "asr-transcripts-new.csv"))
    rc = asr_bind.main(argv)

    assert rc == 0
    assert dsar.calls == [3000]                 # only clip_row 2 (offset 3000) redone
    assert len(calls) == 1
    err = capsys.readouterr().err
    assert "kept 2" in err and "dropped 1" in err
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "1", "2"}


def test_intact_sidecar_drops_nothing_and_warns_nothing(tmp_path, monkeypatch, capsys):
    """A properly-terminated sidecar (every row, including the last, ends in a newline)
    must not drop any row nor print a torn-row warning."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    sidecar = tmp_path / "asr-transcripts.csv"
    _write_csv(sidecar,
               [{"clip_row": "0", "transcript": "prior ok"},
                {"clip_row": "1", "transcript": "prior ok"},
                {"clip_row": "2", "transcript": "prior ok"}],
               asr_bind.TRANSCRIPTS_COLS)

    dsar = FakeDsar()
    calls = []

    def spy_transcribe(wav_path, model, **kw):
        calls.append(wav_path)
        return FakeTranscript("new")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=spy_transcribe)

    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(sidecar),
                 transcripts_out=str(tmp_path / "asr-transcripts-new.csv"))
    rc = asr_bind.main(argv)

    assert rc == 0
    assert dsar.calls == []                     # nothing re-transcribed
    assert len(calls) == 0
    err = capsys.readouterr().err
    assert "dropped" not in err
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "1", "2"}


def test_fsync_called_per_successful_clip_checkpoint(tmp_path, monkeypatch):
    """Each successful clip's checkpoint row must be fsync'd (not just flushed) so it
    survives a crash immediately after -- assert call count, never simulate real power
    loss."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    fsync_calls = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(asr_bind.os, "fsync", spy_fsync)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    assert rc == 0
    assert len(fsync_calls) == 3                # one fsync per successful clip


def test_first_k_clips_all_failing_trips_breaker_and_aborts(tmp_path, monkeypatch, capsys):
    """If the first BREAKER_K clips processed this run ALL fail with zero successes, it
    looks like an environment problem (missing ffmpeg/decoder, bad ASR args), not
    per-clip corruption -- abort the stage (rc 1) instead of burning the whole run
    logging N identical failures, and stop transcribing immediately (don't keep going
    past the Kth failed clip)."""
    n_clips = asr_bind.BREAKER_K + 2   # more clips than the breaker threshold
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=n_clips)
    dsar = FakeDsar()
    calls = []

    def always_fail(wav_path, model, **kw):
        calls.append(wav_path)
        raise OSError("whisperx: ffmpeg not found")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=always_fail)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    assert rc == 1
    assert len(calls) == asr_bind.BREAKER_K      # stopped right at the threshold
    err = capsys.readouterr().err
    assert "environment" in err.lower()
    assert "asr-errors.log" in err
    assert "deciwaves doctor" in err


def test_one_failure_then_successes_keeps_existing_fail_soft_no_breaker(tmp_path, monkeypatch):
    """A single early failure must not arm-then-trip the breaker, and once a success
    happens the breaker must disarm for the rest of the run -- even if later failures
    would otherwise reach BREAKER_K on their own. Existing per-clip fail-soft behavior
    (log + continue) must be unchanged."""
    # 1 fail, 1 success (disarms the breaker), then BREAKER_K more failures -- if the
    # breaker were still armed (or re-armed) these would trip it; they must not.
    n_clips = 2 + asr_bind.BREAKER_K
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=n_clips)
    dsar = FakeDsar()
    calls = []

    def flaky_then_ok(wav_path, model, **kw):
        calls.append(wav_path)
        idx = len(calls)
        if idx == 1 or idx >= 3:
            raise OSError("transient decode hiccup")
        return FakeTranscript("ok")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=flaky_then_ok)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index))

    assert rc == 0
    assert len(calls) == n_clips                 # every clip attempted, none skipped early
    sidecar_rows = list(csv.DictReader(open(tmp_path / "asr-transcripts.csv", encoding="utf-8")))
    assert {r["clip_row"] for r in sidecar_rows} == {"1"}   # only the 2nd clip succeeded
    err_text = (tmp_path / "asr-errors.log").read_text(encoding="utf-8")
    assert err_text.count("transient decode hiccup") == n_clips - 1


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


def test_resume_sidecar_clips_dont_count_toward_breaker(tmp_path, monkeypatch, capsys):
    """Clips skipped via a --transcripts resume sidecar never enter the processing loop,
    so they must never count toward the circuit breaker: 10 already-done clips (from a
    prior run) + 7 new clips that all fail must trip the breaker at exactly the 5th
    NEWLY-processed clip -- not never (if the 10 resumed clips wrongly counted as
    successes and disarmed the breaker) and not immediately (if they wrongly counted as
    failures already partway to BREAKER_K)."""
    n_done = 10
    n_new = 7
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=n_done + n_new)
    sidecar = tmp_path / "asr-transcripts.csv"
    # pre-seed as if a prior run already checkpointed clip_row 0..9 before crashing
    _write_csv(sidecar,
               [{"clip_row": str(i), "transcript": "prior ok"} for i in range(n_done)],
               asr_bind.TRANSCRIPTS_COLS)

    dsar = FakeDsar()
    calls = []

    def always_fail(wav_path, model, **kw):
        calls.append(wav_path)
        raise OSError("whisperx: ffmpeg not found")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=always_fail)

    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(sidecar))
    rc = asr_bind.main(argv)

    assert rc == 1
    assert len(calls) == asr_bind.BREAKER_K      # tripped at the 5th newly-processed clip
    err = capsys.readouterr().err
    assert "environment" in err.lower()


def test_missing_transcripts_path_is_a_clean_usage_error(tmp_path, monkeypatch, capsys):
    """A --transcripts path that doesn't exist must fail as a clean, ASCII usage error
    (argparse's ap.error() convention, exit code 2) -- not an unguarded
    os.path.getsize(path) raising a raw FileNotFoundError traceback."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=1)
    missing = tmp_path / "does-not-exist.csv"
    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(missing))

    with pytest.raises(SystemExit) as exc:
        asr_bind.main(argv)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert str(missing) in err
    assert err.isascii()


def test_torn_sidecar_used_as_both_transcripts_and_transcripts_out_is_healed(tmp_path, monkeypatch):
    """The documented resume recipe reuses the SAME path for --transcripts and
    --transcripts-out. If that sidecar's last row was torn by a crash mid-write, the
    on-disk bytes (unlike the in-memory dict, which drops the torn row) still end
    mid-row; opening it for append must heal the tail first, or the re-transcribed
    row merges with the torn tail into one corrupt row."""
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    sidecar = tmp_path / "asr-transcripts.csv"
    with open(sidecar, "w", newline="", encoding="utf-8") as f:
        f.write("clip_row,transcript\r\n")
        f.write("0,prior ok\r\n")
        f.write("1,prior ok\r\n")
        f.write("2,this is a partial tran")   # no trailing newline: torn

    dsar = FakeDsar()
    calls = []

    def spy_transcribe(wav_path, model, **kw):
        calls.append(wav_path)
        return FakeTranscript("new")

    _patch_asr_stack(monkeypatch, dsar, transcribe_fn=spy_transcribe)

    # SAME path for both flags: the documented resume recipe.
    argv = _argv(tmp_path, catalog, wem_meta, clip_index, transcripts=str(sidecar),
                 transcripts_out=str(sidecar))
    rc = asr_bind.main(argv)

    assert rc == 0
    assert len(calls) == 1                       # only clip_row 2 was re-transcribed

    raw = sidecar.read_bytes()
    assert b"this is a partial tran2" not in raw  # no merged/corrupt row
    rows = list(csv.DictReader(open(sidecar, newline="", encoding="utf-8")))
    assert len(rows) == 4              # 0, 1, the healed (stale) torn row, new clip_row 2
    assert all(len(r) == 2 for r in rows)          # every row parses as exactly 2 fields
    by_row = {r["clip_row"]: r["transcript"] for r in rows}   # later row wins on dup key
    assert by_row["0"] == "prior ok"
    assert by_row["1"] == "prior ok"
    assert by_row["2"] == "new"                    # re-transcribed clip is its own intact row
    assert set(_manifest_clip_rows(tmp_path)) == {"0", "1", "2"}


# ---------------------------------------------------------------------------
# --sample-cap loud reporting (issue #35): a cap that truncates ASR work must never
# be silent -- the stage must state exactly how many ambiguous buckets were left
# untranscribed, and say nothing at all when the cap doesn't actually truncate.
# ---------------------------------------------------------------------------

def test_cap_boundary_exact_cap_buckets_prints_no_message(tmp_path, monkeypatch, capsys):
    """Exactly as many ambiguous buckets as --sample-cap: every bucket is consumed (0
    skipped), so no cap-applied message may appear."""
    n_buckets = 3
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, sample_cap=n_buckets))

    assert rc == 0
    out = capsys.readouterr().out
    assert "SAMPLE CAP" not in out
    assert "left untranscribed" not in out
    assert dsar.calls == [1000, 2000, 3000]   # every bucket's clip transcribed


def test_cap_boundary_fewer_buckets_than_cap_prints_no_message(tmp_path, monkeypatch, capsys):
    """Fewer ambiguous buckets than --sample-cap: the cap never even engages, so no
    message may appear either."""
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets=2)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, sample_cap=5))

    assert rc == 0
    out = capsys.readouterr().out
    assert "SAMPLE CAP" not in out
    assert "left untranscribed" not in out
    assert dsar.calls == [1000, 2000]


def test_cap_one_over_boundary_reports_exact_skipped_count(tmp_path, monkeypatch, capsys):
    """cap+1 ambiguous buckets: exactly ONE bucket must be reported skipped, loudly,
    with the exact count -- not just "cap applied" with no number."""
    n_buckets = 4
    sample_cap = 3
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, sample_cap=sample_cap))

    assert rc == 0
    out = capsys.readouterr().out
    assert "SAMPLE CAP" in out
    assert "1 ambiguous bucket(s) left untranscribed" in out
    assert f"--sample-cap={sample_cap}" in out
    # only the first `sample_cap` buckets' clips were ever decoded/transcribed -- the
    # 4th bucket's clip (offset 4000) must never be attempted.
    assert dsar.calls == [1000, 2000, 3000]


def test_cap_skips_several_buckets_reports_exact_count(tmp_path, monkeypatch, capsys):
    """Several buckets beyond the cap: the reported count must be the exact number
    skipped, not a placeholder or a rounded figure."""
    n_buckets = 7
    sample_cap = 3
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, sample_cap=sample_cap))

    assert rc == 0
    out = capsys.readouterr().out
    assert "4 ambiguous bucket(s) left untranscribed" in out   # 7 - 3 = 4 skipped
    assert dsar.calls == [1000, 2000, 3000]


def test_sample_cap_zero_means_unlimited_full_pass_no_cap_message(tmp_path, monkeypatch, capsys):
    """--sample-cap 0 must mean unlimited: every ambiguous bucket gets transcribed
    and no cap message is printed, however many buckets there are."""
    n_buckets = 5
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, sample_cap=0))

    assert rc == 0
    out = capsys.readouterr().out
    assert "SAMPLE CAP" not in out
    assert dsar.calls == [1000, 2000, 3000, 4000, 5000]   # every bucket's clip transcribed


# ---------------------------------------------------------------------------
# main(): a bad --package (issue #49, mirrors #34's hzd_catalog check) must fail
# actionably, not with a raw FileNotFoundError traceback from hzd_locators.py --
# HzdPackage is deliberately left unmocked here: the check must fire before
# HzdPackage is ever constructed.
# ---------------------------------------------------------------------------

def test_asr_bind_main_missing_package_fails_actionably(tmp_path, monkeypatch, capsys):
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    bad_package = tmp_path / "install_root"  # exists, but no PackFileLocators.bin
    bad_package.mkdir()
    argv = _argv(tmp_path, catalog, wem_meta, clip_index)
    argv[argv.index("--package") + 1] = str(bad_package)   # swap in the bad one

    rc = asr_bind.main(argv)

    assert rc == 1
    captured = capsys.readouterr()
    assert "--hzd-package" in captured.out
    assert "PackFileLocators.bin" in captured.out
    assert captured.err == ""  # no traceback


# ---------------------------------------------------------------------------
# coverage artifact (issue #63): the cap-skip count must land ON DISK, not
# just stdout -- a capped rip used to be indistinguishable from a complete one.
# ---------------------------------------------------------------------------

def test_coverage_artifact_records_cap_skip_on_disk(tmp_path, monkeypatch):
    """THE acceptance test for #63: after a capped bind, a JSON artifact records
    how many ambiguous buckets were left untranscribed (plus the cap used), so
    the GUI coverage bar reads it without scraping stdout."""
    import json
    catalog, wem_meta, clip_index = _write_multi_bucket_fixture(tmp_path, n_buckets=5)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)
    cov = tmp_path / "coverage.json"

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index,
                             sample_cap=2, coverage_out=cov))

    assert rc == 0
    bind = json.loads(cov.read_text(encoding="utf-8"))["bind"]
    assert bind["sample_cap"] == 2
    assert bind["buckets_relevant"] == 5
    assert bind["buckets_attempted"] == 2
    assert bind["buckets_skipped"] == 3
    assert bind["clips_transcribed"] == 2
    assert bind["clips_reused"] == 0
    assert bind["clips_failed"] == 0


def test_coverage_records_untranscribed_shortfall_in_pure_reuse_mode(tmp_path):
    """Pure-reuse mode (--transcripts without --package) leaves clips absent
    from the sidecar untranscribed BY DESIGN -- but silently: not a failure,
    not a cap skip. The coverage section must record that shortfall (issue
    #81), or a partial reuse run is indistinguishable on disk from a complete
    one -- the exact blindness #63 exists to eliminate."""
    import json
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    # sidecar holds only clip 0; clips 1 and 2 are wanted but never transcribed
    sidecar = tmp_path / "prior-transcripts.csv"
    sidecar.write_text("clip_row,transcript\n0,hello there\n", encoding="utf-8")
    cov = tmp_path / "coverage.json"

    rc = asr_bind.main(["--transcripts", str(sidecar),
                        "--clip-index", str(clip_index),
                        "--wem-metadata", str(wem_meta),
                        "--catalog", str(catalog),
                        "--out", str(tmp_path / "asr-manifest.csv"),
                        "--errors", str(tmp_path / "asr-errors.log"),
                        "--transcripts-out", str(tmp_path / "asr-transcripts.csv"),
                        "--coverage-out", str(cov)])

    assert rc == 0
    bind = json.loads(cov.read_text(encoding="utf-8"))["bind"]
    assert bind["clips_reused"] == 1
    assert bind["clips_untranscribed"] == 2
    assert bind["clips_failed"] == 0


def test_coverage_artifact_records_tier_tally_and_totals(tmp_path, monkeypatch):
    """An uncapped bind still writes its section: tier tally + row/bound totals
    (the numbers the final stdout summary prints, persisted)."""
    import json
    catalog, wem_meta, clip_index = _write_fixture(tmp_path, n_clips=3)
    dsar = FakeDsar()
    _patch_asr_stack(monkeypatch, dsar)
    cov = tmp_path / "coverage.json"

    rc = asr_bind.main(_argv(tmp_path, catalog, wem_meta, clip_index, coverage_out=cov))

    assert rc == 0
    bind = json.loads(cov.read_text(encoding="utf-8"))["bind"]
    assert bind["buckets_skipped"] == 0
    assert bind["sample_cap"] == 300  # the stage default, recorded as used
    assert set(bind["tiers"]) == {"S", "1", "2", "E", "3"}
    assert bind["rows"] == sum(bind["tiers"].values())
    assert bind["clips_failed"] == 0
