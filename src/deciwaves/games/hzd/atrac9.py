"""ATRAC9 RIFF helpers for HZDR clips: cheap sample-count read + VGAudio decode."""
from __future__ import annotations
import os
import struct
import subprocess
import tempfile

from deciwaves.engine.atomic_io import atomic_write
from deciwaves.engine.tool_paths import resolve


class Atrac9Error(Exception):
    pass


def trim_riff(data):
    if len(data) < 8 or data[:4] != b"RIFF":
        raise Atrac9Error("not a RIFF stream")
    return data[: struct.unpack("<I", data[4:8])[0] + 8]


def fact_sample_count(header_bytes):
    if header_bytes[:4] != b"RIFF" or header_bytes[8:12] != b"WAVE":
        return None
    p = 12
    while p + 8 <= len(header_bytes):
        cid = header_bytes[p:p+4]
        size = struct.unpack_from("<I", header_bytes, p + 4)[0]
        if cid == b"fact" and p + 8 + 4 <= len(header_bytes):
            return struct.unpack_from("<I", header_bytes, p + 8)[0]
        p += 8 + size + (size & 1)
    return None


def decode_wem_to_wav(wem_bytes, wav_path):
    vgaudio = resolve("DECIWAVES_VGAUDIO", "VGAudioCli")
    payload = trim_riff(wem_bytes)
    with tempfile.NamedTemporaryFile(suffix=".at9", delete=False) as t:
        t.write(payload); tmp = t.name

    def _run(out):
        # atomic_write: VGAudio targets a tmp path moved into place only on
        # success, so a crash mid-decode never poisons the clip_row cache, and
        # two render workers sharing one clip_row can't half-write each other's
        # output (see engine.atomic_io).
        r = subprocess.run([vgaudio, "-i", tmp, "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out):
            raise Atrac9Error(f"VGAudioCli failed: {r.stderr.strip()}")

    try:
        atomic_write(wav_path, _run)
    finally:
        os.unlink(tmp)
