"""ATRAC9 RIFF helpers for HZDR clips: cheap sample-count read + VGAudio decode."""
from __future__ import annotations
import os, shutil, struct, subprocess, tempfile

# Resolution order: explicit env override -> PATH -> bare name. Same pattern/env var
# as games.fw.extract.VGAUDIO (one VGAudio install serves both games).
VGAUDIO = (os.environ.get("DECIWAVES_VGAUDIO")
           or shutil.which("VGAudioCli") or "VGAudioCli")
# resolved at import time — the CLI applies config env before importing stage modules


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
    payload = trim_riff(wem_bytes)
    with tempfile.NamedTemporaryFile(suffix=".at9", delete=False) as t:
        t.write(payload); tmp = t.name
    try:
        r = subprocess.run([VGAUDIO, "-i", tmp, "-o", wav_path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Atrac9Error(f"VGAudioCli failed: {r.stderr.strip()}")
    finally:
        os.unlink(tmp)
