"""Extract one `.core.stream` (Wwise .wem) and decode it to a cached WAV.

Universal trim: a Decima `.core.stream` carries trailing bytes past the declared RIFF size;
vgmstream rejects it until trimmed to u32(data[4:8]) + 8
(.memories/cutscene-audio-per-scene-voice-track.md).
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import subprocess
import wave

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VGMSTREAM = os.path.join(_REPO, "vendor", "vgmstream", "vgmstream-cli.exe")


class ClipError(Exception):
    pass


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
    # trim (and its wrong duration) from a prior run (#42). Check BEFORE the ffmpeg
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
    preserved (normalize canonicalizes later). Raises ClipError on failure."""
    parts = "".join(
        f"[0:a]atrim=start={a}:end={b},asetpts=N/SR/TB[k{i}];"
        for i, (a, b) in enumerate(keeps))
    labels = "".join(f"[k{i}]" for i in range(len(keeps)))
    fc = f"{parts}{labels}concat=n={len(keeps)}:v=0:a=1[out]"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[out]", dst],
        capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(dst):
        raise ClipError(f"atrim-concat failed for {src}: {proc.stderr[-300:]}")


def apply_keep_spans(src, spans, cache_dir):
    """Trim `src` to the union of `spans` ([(start, end), ...] seconds), the
    speech-region keep-spans from cutscene trim (#52). Returns (path, duration).
    Cache key folds the spans so a different span set misses the cache instead of
    returning a stale trim (#42 contract). Empty `spans` is a caller bug (dropped
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
    try:
        proc = subprocess.run([vgmstream, "-o", wav_path, wem_path],
                              capture_output=True, text=True)
    finally:
        if os.path.isfile(wem_path):
            os.remove(wem_path)
    if proc.returncode != 0 or not os.path.isfile(wav_path):
        raise ClipError(f"vgmstream failed for {stream_path}: {proc.stderr.strip()}")
    return wav_path, wav_duration_seconds(wav_path)
