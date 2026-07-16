import os
import threading

import pytest

from deciwaves.engine.atomic_io import atomic_write, _tmp_path_for


def _stray_files(tmp_path, dst):
    """Anything left in tmp_path besides the final dst -- i.e. a leftover
    tmp/partial file."""
    return [f for f in os.listdir(tmp_path) if os.path.join(str(tmp_path), f) != dst]


def test_atomic_write_success_creates_dst_with_content(tmp_path):
    dst = str(tmp_path / "out.wav")

    def write_fn(tmp):
        assert tmp != dst
        assert tmp.endswith(".wav"), "tmp must keep dst's extension for ffmpeg/vgmstream"
        assert os.path.dirname(tmp) == os.path.dirname(dst)
        with open(tmp, "wb") as f:
            f.write(b"RIFF-COMPLETE-DATA")

    atomic_write(dst, write_fn)

    assert os.path.isfile(dst)
    with open(dst, "rb") as f:
        assert f.read() == b"RIFF-COMPLETE-DATA"
    assert _stray_files(tmp_path, dst) == [], "no tmp file must linger after success"


def test_atomic_write_interrupted_mid_stream_does_not_poison_cache(tmp_path):
    """Real-world repro: Ctrl-C (or a crash) partway through ffmpeg/vgmstream
    writing the destination leaves a truncated file that an `isfile and
    getsize > 44`-style cache check would treat as valid forever. The fix
    writes to a tmp path and only os.replace()s it into place on success, so
    an interruption must never leave anything at the final `dst`."""
    dst = str(tmp_path / "out.wav")

    def write_fn(tmp):
        with open(tmp, "wb") as f:
            f.write(b"PARTIAL-TRUNCATED-BYTES-THAT-WOULD-PASS-A-SIZE-CHECK")
        raise KeyboardInterrupt("simulated interrupt mid-write")

    with pytest.raises(KeyboardInterrupt):
        atomic_write(dst, write_fn)

    assert not os.path.isfile(dst), \
        "interrupted write must not poison the cache at the final path"
    assert _stray_files(tmp_path, dst) == [], "tmp file must be cleaned up on failure"


def test_atomic_write_failure_does_not_clobber_existing_valid_cache(tmp_path):
    """A later failing re-run (e.g. a decoder crash on retry) must not destroy
    a previously-good cached file at dst."""
    dst = str(tmp_path / "out.wav")
    with open(dst, "wb") as f:
        f.write(b"GOOD-PREVIOUSLY-CACHED-CONTENT")

    def write_fn(tmp):
        with open(tmp, "wb") as f:
            f.write(b"BAD")
        raise RuntimeError("decode failed")

    with pytest.raises(RuntimeError):
        atomic_write(dst, write_fn)

    with open(dst, "rb") as f:
        assert f.read() == b"GOOD-PREVIOUSLY-CACHED-CONTENT"
    assert _stray_files(tmp_path, dst) == []


def test_atomic_write_tmp_path_lives_in_destination_directory(tmp_path):
    """tmp must be a sibling of dst (same directory / same volume) so the
    final move is an atomic os.replace rename on Windows, not a cross-volume
    copy."""
    dst = str(tmp_path / "sub" / "out.wav")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    seen_tmp_dir = []

    def write_fn(tmp):
        seen_tmp_dir.append(os.path.dirname(tmp))
        with open(tmp, "wb") as f:
            f.write(b"x")

    atomic_write(dst, write_fn)
    assert seen_tmp_dir[0] == os.path.dirname(dst)


# --- collision-proofing under concurrency (issue #41) ---------------------
# When the decode loops run in a worker pool, two workers can decode the same
# cache path at once (e.g. two DS lines sharing one cutscene stream, or two
# spine items sharing one HZD clip_row). A DETERMINISTIC tmp name would make
# both workers write the SAME tmp file and os.replace() it out from under each
# other -- interleaved bytes / a vanished tmp. The tmp name must be unique per
# call so two concurrent writes to one dst never share a tmp path.

def test_tmp_path_is_unique_per_call_but_keeps_extension_and_dir():
    dst = os.path.join("some", "dir", "clip.wav")
    a = _tmp_path_for(dst)
    b = _tmp_path_for(dst)
    assert a != b, "two calls must yield distinct tmp paths (collision-proof)"
    for t in (a, b):
        assert t.endswith(".wav"), "tmp must keep dst's extension for ffmpeg/vgmstream"
        assert os.path.dirname(t) == os.path.dirname(dst), "tmp must be a sibling of dst"
        assert t != dst


def test_concurrent_atomic_writes_to_same_dst_do_not_corrupt(tmp_path):
    """Many threads atomically writing the SAME dst with the SAME content must
    end with an intact file equal to that content and no leftover tmp files --
    never a half-written / interleaved result."""
    dst = str(tmp_path / "clip.wav")
    payload = b"COMPLETE-IDENTICAL-PAYLOAD" * 100
    barrier = threading.Barrier(12)
    errors = []

    def writer():
        try:
            barrier.wait()

            def write_fn(tmp):
                with open(tmp, "wb") as f:
                    f.write(payload)

            atomic_write(dst, write_fn)
        except Exception as e:  # pragma: no cover - only on a real race bug
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"a concurrent atomic_write raced: {errors}"
    with open(dst, "rb") as f:
        assert f.read() == payload, "final file must be the whole, uncorrupted payload"
    assert _stray_files(tmp_path, dst) == [], "no tmp file may linger after the race"
