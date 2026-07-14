"""Resolve a cutscene scene to its English Wwise voice-track stream paths.

Cutscene dialogue has null per-line sound refs; the audio is per-scene (sometimes
per-character / per-camera-sub-cut) Wwise voice tracks under
`ds/sounds/wwise_cinematics_sound_resource/`. See
`.memories/cutscene-audio-per-scene-voice-track.md` for the full linkage.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

WWISE_CINE_ROOT = "ds/sounds/wwise_cinematics_sound_resource"

_CSDIR_RE = re.compile(r"sq_(cs\d+)_")
_SUBCUT_RE = re.compile(r"(sq_cs\d+_s\d+)_(c\d+\w*)$")
_SUBCUT_CORE_RE = re.compile(
    rf"^{re.escape(WWISE_CINE_ROOT)}/cs\d+/(sq_cs\d+_s\d+\w*)/c\d+\w*/\1_c\d+\w*_sound$")
_PRINTABLE_RE = re.compile(rb"[\x20-\x7e]{6,}")
_ENGLISH = ".english"


def candidate_sound_cores(scene: str) -> list[str]:
    """Candidate `*_sound` core virtual paths (no extension) for a cutscene scene.

    Always the flat form `<root>/<csNN>/<scene>/<scene>_sound`; for sub-cut scenes
    (`sq_csNN_sNNNNN_cNNN`) also the nested form where scene and cut are separate dirs.
    """
    m = _CSDIR_RE.match(scene)
    if not m:
        return []
    root = f"{WWISE_CINE_ROOT}/{m.group(1)}"
    cands = [f"{root}/{scene}/{scene}_sound"]
    sub = _SUBCUT_RE.match(scene)
    if sub:
        base, cut = sub.group(1), sub.group(2)
        cands.append(f"{root}/{base}/{cut}/{scene}_sound")
    return cands


def english_voice_tracks(sound_core_bytes: bytes) -> list[str]:
    """English dialogue voice-track virtual paths embedded in a `*_sound` core.

    Skips music/m_and_e/sfx tracks and non-English languages, trims any trailing
    field byte glued onto the path, and de-dupes while preserving order.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in _PRINTABLE_RE.finditer(sound_core_bytes):
        s = m.group().decode("latin1")
        i = s.find(_ENGLISH)
        if i == -1:
            continue
        path = s[: i + len(_ENGLISH)]
        start = path.rfind(WWISE_CINE_ROOT)  # strip any leading length-prefix junk
        if start == -1:
            continue
        path = path[start:]
        if "/wav/english/windows/" not in path or "voice" not in path or "track" not in path:
            continue
        if path not in seen:
            seen.add(path)
            found.append(path)
    return found


def subcut_core_index(listing: Iterable[str]) -> dict[str, list[str]]:
    """Map base scene -> per-cut `*_sound` cores, from a packfile path listing.

    Covers scenes whose audio is split across camera sub-cuts (e.g. cs71/cs80) where
    the catalog names only the base scene. Flat single-dir cores are not indexed here
    (those are handled by `candidate_sound_cores`).
    """
    index: dict[str, list[str]] = {}
    for path in listing:
        m = _SUBCUT_CORE_RE.match(path.strip())
        if m:
            index.setdefault(m.group(1), []).append(path.strip())
    return index


@dataclass
class SceneAudio:
    """Resolution result for one cutscene scene.

    status is one of: resolved | no_sound_core | no_voice_track | no_stream.
    voice_tracks holds the existing `*.core.stream` paths (empty unless resolved).
    """
    scene: str
    status: str
    voice_tracks: list[str] = field(default_factory=list)


def resolve_scene(
    scene: str,
    read_core: Callable[[str], bytes],
    path_exists: Callable[[str], bool],
    extra_candidates: Iterable[str] = (),
) -> SceneAudio:
    """Resolve a cutscene scene to its existing English voice-track stream paths.

    Aggregates English voice tracks across every candidate `*_sound` core that exists
    (the flat/nested-sub-cut conventions plus any `extra_candidates`, e.g. per-cut
    cores from `subcut_core_index`). `read_core(vpath)` returns core bytes;
    `path_exists(full_path)` tests whether a virtual path (with extension) is present.
    """
    candidates = candidate_sound_cores(scene) + list(extra_candidates)
    existing = [c for c in candidates if path_exists(c + ".core")]
    if not existing:
        return SceneAudio(scene, "no_sound_core")

    tracks: list[str] = []
    seen: set[str] = set()
    for core in existing:
        for t in english_voice_tracks(read_core(core)):
            if t not in seen:
                seen.add(t)
                tracks.append(t)
    if not tracks:
        return SceneAudio(scene, "no_voice_track")

    streams = [t + ".core.stream" for t in tracks if path_exists(t + ".core.stream")]
    if streams:
        return SceneAudio(scene, "resolved", streams)
    return SceneAudio(scene, "no_stream")


TRACKS_CSV_COLUMNS = ["scene", "status", "track_index", "voice_track_stream"]


def write_tracks_csv(results: Iterable[SceneAudio], out_path: str) -> None:
    """Write one row per (scene, voice track). Scenes without a resolved track
    still emit a single row (empty stream) so Phase D sees every cutscene scene."""
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKS_CSV_COLUMNS)
        w.writeheader()
        for r in results:
            if r.voice_tracks:
                for i, stream in enumerate(r.voice_tracks):
                    w.writerow({"scene": r.scene, "status": r.status,
                                "track_index": i, "voice_track_stream": stream})
            else:
                w.writerow({"scene": r.scene, "status": r.status,
                            "track_index": "", "voice_track_stream": ""})


def packindex_accessors(idx):
    """Build (read_core, path_exists) callables backed by a PackIndex.

    path_exists is a cheap hash-membership test (no extraction). It reads PackIndex's
    internal hash table directly because PackIndex exposes no public existence check
    for an arbitrary path-with-extension (`has_core` only appends `.core`).
    """
    from deciwaves.engine.pack.bin_archive import file_hash

    def path_exists(full_path):
        return file_hash(full_path) in idx._by_hash

    return idx.read_core, path_exists


def cutscene_scenes_from_catalog(catalog_path):
    """Distinct cutscene scene names from a Phase-B catalog.csv, in first-seen order."""
    seen = {}
    with open(catalog_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("category") == "cutscene" and row["scene"] not in seen:
                seen[row["scene"]] = None
    return list(seen)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--catalog", default="out/catalog.csv")
    ap.add_argument("--file-list", default="out/data-file-list.txt")
    ap.add_argument("--out", default="out/cutscene_tracks.csv")
    args = ap.parse_args(argv)

    from deciwaves.engine.pack.bin_index import PackIndex

    scenes = cutscene_scenes_from_catalog(args.catalog)
    listing = open(args.file_list, encoding="utf-8").read().splitlines()
    subcuts = subcut_core_index(listing)
    idx = PackIndex(args.data_dir, args.oodle)
    read_core, path_exists = packindex_accessors(idx)

    results = [resolve_scene(s, read_core, path_exists, subcuts.get(s, ()))
               for s in scenes]
    write_tracks_csv(results, args.out)

    by_status = {}
    tracks = 0
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        tracks += len(r.voice_tracks)
    resolved = by_status.get("resolved", 0)
    print(f"{len(scenes)} cutscene scenes; {resolved} resolved ({tracks} voice tracks)")
    for status, n in sorted(by_status.items()):
        print(f"  {status}: {n}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
