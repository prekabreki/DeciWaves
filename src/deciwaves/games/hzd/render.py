"""HZD render: asr-manifest.csv -> ordered story MP3 reel (<=290 MB files).

Two modes, both bound-story-lines-only, ordered by quest/scene then in-scene
line_index:
  * ``--spine-only``: main-quest lines only (scene `mq##`), sorted purely on quest
    number -- main quests already sort cleanly into canonical story order
    (papooserider -> giftfromthepast -> ... -> thefaceofextinction), so no
    episode_map is needed for this narrower reel.
  * default: the full story reel -- main quests PLUS every side/DLC scene, interleaved
    at its unlock point via ``games.hzd.episode_map.HZD_EPISODE_MAP`` (questline
    prefix -> unlock rank); a questline absent from that map sorts last rather than
    being dropped.

Reuses engine.render's game-agnostic assembly kit (accumulate_episode_seconds ->
assemble_reels -> MP3 128k, tracklist sidecars); the HZD-specific part is decoding each
clip from package.01 by (offset, length) via VGAudio.

    deciwaves hzd render --package <pkg dir> [--spine-only]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import wave
from dataclasses import dataclass

from deciwaves.engine.render import (
    accumulate_episode_seconds, assemble_reels, budget_seconds, format_ts, ReelColumns,
)
from deciwaves.engine.parallel import KeyedLocks, default_jobs
from deciwaves.engine.pack.hzd_package import HzdPackage
from deciwaves.games.hzd.atrac9 import decode_wem_to_wav, Atrac9Error
from deciwaves.games.hzd.catalog import load_catalog_dict
from deciwaves.games.hzd.profile import VOICE_ARCHIVE as ARCHIVE

BOUND_TIERS = {"S", "1", "2", "E"}   # E = recovered by bucket elimination (mis-bind fix)


@dataclass
class SpineItem:
    episode: int        # dense rank of the quest scene (packing unit)
    scene: str
    line_index: int
    speaker: str
    subtitle: str
    line_id: str
    clip_row: int
    offset: int
    a_bytes: int


def mq_rank(scene: str):
    """Story-order key for a main-quest scene, or None if not a main quest.

    Handles `mq04_x` -> 4.0, `mq01_5_x` -> 1.5, `mq15.5_x` -> 15.5, `mq16_x` -> 16.0.
    """
    m = re.match(r"mq(\d+)(?:[._](\d+))?(?:_|\.|$)", scene)
    if not m:
        return None
    major, minor = m.group(1), m.group(2)
    return int(major) + (int(minor) / 10.0 if minor else 0.0)


UNMAPPED_RANK = 999.0   # side/DLC questline absent from the episode_map -> sort last, never drop


def story_rank(scene: str, episode_map):
    """Story-order key for a scene.

    Main quests use their `mq#`. With an ``episode_map`` (questline-prefix -> unlock
    rank), side/DLC scenes interleave at their unlock point; unmapped questlines sort
    last (never dropped). ``episode_map=None`` is main-quest-spine mode: non-mq -> None.
    """
    r = mq_rank(scene)
    if r is not None:
        return r
    if episode_map is None:
        return None
    return episode_map.get(scene.split("/")[0], UNMAPPED_RANK)


def _line_seq(line_id: str):
    """Embedded sequence numbers of a line_id, after the leading quest code.

    `MQ010_cut_Prologue_Dial_020` -> (20,); `MQ04_IC_Bast_..._01` -> (1,). Used to order
    scenes within a quest where they share a continuous numbering (e.g. the prologue's
    thewalk Dial_020.. then namingceremony Dial_220..). Lines with no number sort last.
    """
    stem = re.sub(r"^[A-Za-z]+\d+_?", "", line_id, count=1)
    return tuple(int(n) for n in re.findall(r"\d+", stem)) or (10 ** 9,)


def build_spine(manifest_rows, catalog, clip_index, episode_map=None) -> list[SpineItem]:
    """Ordered playlist of bound story lines, in story order.

    ``catalog``: line_id -> row dict (category, subtitle_en, speaker_name, scene, line_index).
    ``clip_index``: int clip_row -> {offset, a_bytes}. Lines whose clip is absent are skipped.
    ``episode_map``: None = main-quest spine only; else questline-prefix -> unlock rank,
    interleaving side/DLC content (nothing is dropped — unmapped questlines sort last).
    """
    items = []
    seen = set()
    for r in manifest_rows:
        if r["tier"] not in BOUND_TIERS:
            continue
        lid = r["line_id"]
        if not lid or lid in seen:
            continue
        meta = catalog.get(lid)
        if not meta:
            continue
        if meta["category"] == "ambient" or not meta["subtitle_en"].strip():
            continue
        rank = story_rank(meta["scene"], episode_map)
        if rank is None:                       # main-quest spine mode skips non-mq
            continue
        cr = int(r["clip_row"])
        clip = clip_index.get(cr)
        if not clip:                           # no decode coords -> can't render
            continue
        seen.add(lid)
        items.append((rank, meta, lid, cr, int(clip["offset"]), int(clip["a_bytes"])))

    # scene order within a quest: by the scene's min embedded line-sequence (handles the
    # prologue's thewalk->namingceremony), then scene name as a stable tiebreak.
    scene_seq = {}
    for _, meta, lid, *_ in items:
        s = meta["scene"]
        seq = _line_seq(lid)
        if s not in scene_seq or seq < scene_seq[s]:
            scene_seq[s] = seq

    # order by quest rank, scene's sequence position, scene name, then in-scene line_index
    items.sort(key=lambda t: (t[0], scene_seq[t[1]["scene"]], t[1]["scene"],
                              int(t[1]["line_index"]), t[2]))

    # dense episode index per distinct quest scene, in order
    ep_of = {}
    spine = []
    for rank, meta, lid, cr, off, ab in items:
        ep_of.setdefault(meta["scene"], len(ep_of))
        spine.append(SpineItem(
            episode=ep_of[meta["scene"]], scene=meta["scene"],
            line_index=int(meta["line_index"]), speaker=meta["speaker_name"],
            subtitle=meta["subtitle_en"], line_id=lid, clip_row=cr,
            offset=off, a_bytes=ab))
    return spine


def decode_spine_clips(spine, dsar, cache_dir, errors_path, jobs=1):
    """Decode each clip once (cached by clip_row) into ``cache_dir/<clip_row>.wav``.

    Fail-soft per clip: a decode failure (``Atrac9Error``, ``OSError``,
    ``wave.Error``) or a bad archive read (``ValueError`` -- see the
    dsar_archive/fw_stream read hardening) is logged to *errors_path* with the
    line id and clip row, then skipped -- never aborting the whole render.

    ``jobs`` decodes that many clips concurrently (each a VGAudio subprocess);
    ``jobs=1`` (default) is the old serial path. ``dsar.read`` reopens the archive
    per call so it is safe under the pool; a per-clip_row lock serializes the two
    spine items that can share one clip_row so the shared cache file is written
    exactly once (see engine.parallel.KeyedLocks).

    Returns ``(decoded, ep_secs, skipped)``: ``decoded`` maps
    ``line_id -> (wav_path, duration_seconds)``; ``ep_secs`` is the
    per-episode accumulated duration ``pack_episodes`` packs against. Thin wrapper
    around engine.render's shared ``accumulate_episode_seconds``: this function
    supplies the HZD-specific per-clip decode, the gap/error bookkeeping is shared.
    """
    clip_locks = KeyedLocks()

    def dur_of(s):
        wav = os.path.join(cache_dir, f"{s.clip_row}.wav")
        if not (os.path.isfile(wav) and os.path.getsize(wav) > 44):
            with clip_locks(wav):
                if not (os.path.isfile(wav) and os.path.getsize(wav) > 44):
                    decode_wem_to_wav(dsar.read(s.offset, s.a_bytes), wav)
        with wave.open(wav) as w:
            dur = w.getnframes() / float(w.getframerate())
        return wav, dur

    decoded, ep_secs, skipped = accumulate_episode_seconds(
        spine, dur_of, gap_key=lambda s: s.scene, err_key=lambda s: s.clip_row,
        errors_path=errors_path, catch=(Atrac9Error, OSError, wave.Error, ValueError),
        jobs=jobs)
    return decoded, ep_secs, skipped


def _load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render HZD main-quest spine to MP3")
    ap.add_argument("--package", required=True)
    ap.add_argument("--manifest", default="out/hzd/asr-manifest.csv")
    ap.add_argument("--catalog", default="out/hzd/catalog.csv")
    ap.add_argument("--clip-index", default="out/hzd/clip-index.csv")
    ap.add_argument("--out-dir", default="out/hzd/audio")
    ap.add_argument("--cache", default="out/hzd/wav-cache")
    ap.add_argument("--errors", default="out/hzd/render-errors.log")
    ap.add_argument("--spine-only", action="store_true",
                    help="render only the main-quest spine (skip side/DLC interleaving)")
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="number of clips to decode concurrently (each spawns one "
                         f"VGAudioCli). Default min(8, cpu_count)={default_jobs()}; "
                         "--jobs 1 forces the old serial decode")
    a = ap.parse_args(argv)

    from deciwaves.games.hzd.profile import hzd_package_error
    err = hzd_package_error(a.package)
    if err:
        print(err)
        return 1

    catalog = load_catalog_dict(a.catalog)
    clip_index = {int(c["clip_row"]): c for c in _load_csv(a.clip_index)}
    if a.spine_only:
        episode_map = None
    else:
        from deciwaves.games.hzd.episode_map import HZD_EPISODE_MAP
        episode_map = HZD_EPISODE_MAP
    spine = build_spine(_load_csv(a.manifest), catalog, clip_index, episode_map=episode_map)
    kind = "main-quest spine" if a.spine_only else "full story reel"
    print(f"{kind}: {len(spine)} lines across {len({s.episode for s in spine})} scenes")

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)

    pkg = HzdPackage(a.package)
    dsar = pkg.dsar_for(ARCHIVE)

    decoded, ep_secs, skipped = decode_spine_clips(spine, dsar, a.cache, a.errors, jobs=a.jobs)
    if skipped:
        print(f"decode: {skipped} clips skipped (see {a.errors})")

    stem = "hzd_mainquest" if a.spine_only else "hzd_story_reel"
    columns = ReelColumns(
        header=["timestamp", "scene", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.scene, s.speaker, s.subtitle, s.line_id])
    assemble_reels(
        spine, ep_secs, decoded, out_dir=a.out_dir, cache_dir=a.cache, stem=stem,
        columns=columns, budget=budget_seconds(), gap_key=lambda s: s.scene)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
