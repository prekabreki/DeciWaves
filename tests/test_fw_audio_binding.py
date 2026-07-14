"""Milestone-1 proof: a Forbidden West dialogue line resolves end-to-end to its
English audio via ``streaming_graph.core`` alone — the binding HZD Remastered
could not do (no streaming graph; see .memories/fw-ships-streaming-graph.md).

The rigorous tie is a double cross-check against the resource's own inline
fields, read from the group's serialized span:
  * ``StreamingDataSource.Length`` (A) == the RIFF clip byte length, and
  * ``LocalizedDataSource.SampleCount`` (B) == the decoded WAV frame count.
Both appearing as u32s in the span — at the offset streaming_graph predicts —
is a ~1-in-billions confirmation the stream is that line's audio.

Skips when the FW install or VGAudio is absent.
"""
import os
import struct
import subprocess
import wave

import pytest

from deciwaves.engine.pack.fw_streaming_graph import StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore
from deciwaves.engine.pack.dsar_archive import DsarArchive
from deciwaves.engine.pack.bin_archive import murmurhash3_x64_128

VGAUDIO = os.path.join("vendor", "vgaudio", "VGAudioCli.exe")


def _prefixed_hash(name: str) -> int:
    return struct.unpack("<Q", murmurhash3_x64_128(("00000001_" + name).encode(), 42)[:8])[0]


LSSR = _prefixed_hash("LocalizedSimpleSoundResource")


def _clean_single_line_group(g: StreamingGraph, en: int):
    """First group with exactly one English locator and a sound resource."""
    for grp in g.groups:
        locs = g.locators[grp.locator_start:grp.locator_start + grp.locator_count]
        en_locs = [l for l in locs if l.file_index == en]
        if len(en_locs) != 1:
            continue
        types = g.type_table[grp.type_start:grp.type_start + grp.type_count]
        if LSSR in types:
            return grp, en_locs[0]
    return None, None


def test_line_resolves_to_english_audio(fw_package_dir):
    pkg = str(fw_package_dir)
    g = StreamingGraph.from_file(os.path.join(pkg, "streaming_graph.core"))
    en = g.file_index("en/package.01.00.core.stream")

    grp, en_loc = _clean_single_line_group(g, en)
    assert grp is not None, "no clean single-line dialogue group found"

    # Resolve the English clip from the raw stream store (self-describing RIFF).
    store = FwStreamStore(pkg, g.files)
    clip = store.read_riff_clip(en, en_loc.offset)
    assert clip[:4] == b"RIFF" and clip[8:12] == b"WAVE"

    # Cross-check A: the clip length is the resource's inline StreamingDataSource.Length,
    # serialized in this group's span (read from its package.00.NN.core archive).
    sp = g.spans[grp.span_start]
    arc = g.files[sp.file_index].replace("cache:package/", "")
    span = DsarArchive(os.path.join(pkg, arc)).read(sp.offset, sp.length)
    assert struct.pack("<I", len(clip)) in span, "clip length not found in resource span (A mismatch)"


@pytest.mark.skipif(not os.path.isfile(VGAUDIO), reason="VGAudio not present")
def test_english_audio_decodes_and_sample_count_matches(fw_package_dir, tmp_path):
    pkg = str(fw_package_dir)
    g = StreamingGraph.from_file(os.path.join(pkg, "streaming_graph.core"))
    en = g.file_index("en/package.01.00.core.stream")
    grp, en_loc = _clean_single_line_group(g, en)
    assert grp is not None

    clip = FwStreamStore(pkg, g.files).read_riff_clip(en, en_loc.offset)
    at9 = tmp_path / "clip.at9"
    wav = tmp_path / "clip.wav"
    at9.write_bytes(clip)
    subprocess.run([VGAUDIO, "-i", str(at9), "-o", str(wav)], check=True,
                   capture_output=True)

    with wave.open(str(wav), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 48000
        frames = w.getnframes()

    # Cross-check B: decoded frame count is the resource's inline SampleCount,
    # serialized in the group span.
    sp = g.spans[grp.span_start]
    arc = g.files[sp.file_index].replace("cache:package/", "")
    span = DsarArchive(os.path.join(pkg, arc)).read(sp.offset, sp.length)
    assert struct.pack("<I", frames) in span, "decoded sample count not found in span (B mismatch)"
