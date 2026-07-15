"""Extract one `.core.stream` (Wwise .wem) and decode it to a cached WAV.

Universal trim: a Decima `.core.stream` carries trailing bytes past the declared RIFF size;
vgmstream rejects it until trimmed to u32(data[4:8]) + 8
(see .memories/ds-cutscene-audio.md).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import wave

from deciwaves.engine.atomic_io import atomic_write

# Resolution order: explicit env override -> PATH -> bare name (fails loudly at
# call time if truly absent). No more repo-relative vendor/ default -- tool setup
# is the caller's job (see README's Install/Troubleshooting sections); Task 6's
# CLI prepends a tools dir to PATH.
VGMSTREAM = (os.environ.get("DECIWAVES_VGMSTREAM")
             or shutil.which("vgmstream-cli") or "vgmstream-cli")
# resolved at import time — the CLI applies config env before importing stage modules


class ClipError(Exception):
    pass


def _returncode_detail(returncode):
    """Format a subprocess exit code for a ClipError message.

    Hex is appended for codes >= 2**16 (Windows NTSTATUS-range values, e.g. a
    crashed vgmstream-cli reporting 3221225781 / 0xC0000135 STATUS_DLL_NOT_FOUND)
    so the failure is recognizable at a glance; smaller/ordinary exit codes are
    left as plain decimal.
    """
    if returncode is not None and abs(returncode) >= 2 ** 16:
        return f"exit code {returncode} (0x{returncode & 0xFFFFFFFF:08X})"
    return f"exit code {returncode}"


def trim_riff(data):
    if len(data) < 8 or data[:4] != b"RIFF":
        raise ClipError("not a RIFF stream")
    size = struct.unpack("<I", data[4:8])[0]
    return data[: size + 8]


def wav_duration_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _key(stream_path):
    return hashlib.sha1(stream_path.encode("utf-8")).hexdigest()


def _detect_silences(src, threshold_db, min_silence):
    """Return [(start, end), ...] silence spans >= min_silence at threshold_db,
    via ffmpeg silencedetect."""
    proc = subprocess.run(
        ["ffmpeg", "-i", src, "-af",
         f"silencedetect=noise={threshold_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", proc.stderr)]
    return list(zip(starts, ends))  # silencedetect pairs them in order


def trim_long_silences(src, cache_dir, min_silence=10.0, threshold_db=-30.0, keep=0.75):
    """Collapse every silence >= `min_silence` seconds down to `keep` seconds.

    Cutscene whole-scene voice tracks carry minutes of dead air between sparse
    lines; lines have no such gaps and pass through untouched. Channel layout and
    sample rate are preserved (normalize handles canonicalization later); the
    returned duration reflects the trimmed audio so the tracklist stays accurate.
    Returns (path, duration). Clips with no long silence are returned as-is.
    """
    # Cache key folds the trim params: a different min_silence/threshold_db/keep is a
    # different result, so changing them must miss the cache instead of returning the stale
    # trim (and its wrong duration) from a prior run. Check BEFORE the ffmpeg
    # silencedetect pass so a cache hit costs nothing to decode.
    os.makedirs(cache_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    tag = hashlib.sha1(
        f"{stem}|min={min_silence}|db={threshold_db}|keep={keep}".encode("utf-8")
    ).hexdigest()[:12]
    dst = os.path.join(cache_dir, f"{stem}.{tag}{ext or '.wav'}")
    if os.path.isfile(dst) and os.path.getsize(dst) > 44:
        return dst, wav_duration_seconds(dst)

    silences = _detect_silences(src, threshold_db, min_silence)
    if not silences:
        return src, wav_duration_seconds(src)

    total = wav_duration_seconds(src)
    # Keep all non-silence plus `keep` s of each long gap; drop [s+keep, e].
    keeps, prev = [], 0.0
    for s, e in silences:
        end = min(s + keep, e)
        if end > prev:
            keeps.append((prev, end))
        prev = e
    if total > prev:
        keeps.append((prev, total))

    _atrim_concat(src, keeps, dst)
    return dst, wav_duration_seconds(dst)


def _atrim_concat(src, keeps, dst):
    """Build `dst` by concatenating the [start, end] intervals `keeps` of `src`
    via an ffmpeg atrim+concat filter graph. Channel layout / sample rate are
    preserved (normalize canonicalizes later). Raises ClipError on failure.

    Written via atomic_write: ffmpeg targets a tmp path, moved into place at
    `dst` only on success, so an interrupted/failed run never leaves a
    truncated file at the cache path (see engine.atomic_io)."""
    parts = "".join(
        f"[0:a]atrim=start={a}:end={b},asetpts=N/SR/TB[k{i}];"
        for i, (a, b) in enumerate(keeps))
    labels = "".join(f"[k{i}]" for i in range(len(keeps)))
    fc = f"{parts}{labels}concat=n={len(keeps)}:v=0:a=1[out]"

    def _run(tmp):
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[out]", tmp],
            capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.isfile(tmp):
            raise ClipError(f"atrim-concat failed for {src}: {proc.stderr[-300:]}")

    atomic_write(dst, _run)


def apply_keep_spans(src, spans, cache_dir):
    """Trim `src` to the union of `spans` ([(start, end), ...] seconds), the
    speech-region keep-spans from cutscene trim. Returns (path, duration).
    Cache key folds the spans so a different span set misses the cache instead of
    returning a stale trim. Empty `spans` is a caller bug (dropped
    tracks are skipped upstream) -> ClipError."""
    if not spans:
        raise ClipError(f"apply_keep_spans called with no spans for {src}")
    os.makedirs(cache_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    key = ";".join(f"{a}:{b}" for a, b in spans)
    tag = hashlib.sha1(f"{stem}|spans={key}".encode("utf-8")).hexdigest()[:12]
    dst = os.path.join(cache_dir, f"{stem}.{tag}{ext or '.wav'}")
    if os.path.isfile(dst) and os.path.getsize(dst) > 44:
        return dst, wav_duration_seconds(dst)
    _atrim_concat(src, spans, dst)
    return dst, wav_duration_seconds(dst)


def clip_wav(idx, stream_path, cache_dir, vgmstream=VGMSTREAM):
    os.makedirs(cache_dir, exist_ok=True)
    wav_path = os.path.join(cache_dir, _key(stream_path) + ".wav")
    if os.path.isfile(wav_path) and os.path.getsize(wav_path) > 44:
        return wav_path, wav_duration_seconds(wav_path)
    try:
        raw = idx.read(stream_path)
    except KeyError as e:
        raise ClipError(f"stream not in install: {stream_path}") from e
    wem_path = os.path.join(cache_dir, _key(stream_path) + ".wem")
    try:
        trimmed = trim_riff(raw)
    except ClipError as e:
        raise ClipError(f"bad RIFF in {stream_path}: {e}") from e
    with open(wem_path, "wb") as f:
        f.write(trimmed)

    def _run(tmp):
        proc = subprocess.run([vgmstream, "-o", tmp, wem_path],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.isfile(tmp):
            detail = _returncode_detail(proc.returncode)
            stderr = (proc.stderr or "").strip()
            if stderr:
                detail = f"{detail}; stderr: {stderr}"
            raise ClipError(f"vgmstream failed for {stream_path}: {detail}")

    try:
        # atomic_write: vgmstream targets a tmp path, moved into place only on
        # success, so a crash/interrupt mid-decode never poisons the cache
        # with a truncated .wav (see engine.atomic_io).
        atomic_write(wav_path, _run)
    finally:
        if os.path.isfile(wem_path):
            os.remove(wem_path)
    return wav_path, wav_duration_seconds(wav_path)
