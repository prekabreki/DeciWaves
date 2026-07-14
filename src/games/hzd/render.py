"""HZD #20 render: asr-manifest.csv -> ordered main-quest MP3 reel (<=290 MB files).

Main-quest spine only: bound story lines whose scene is a main quest (`mq##`), ordered
by quest number then in-scene line_index. Quests sort cleanly into canonical story order
(papooserider -> giftfromthepast -> ... -> thefaceofextinction), so no episode_map or
transcript anchoring is needed for this spine (side/DLC content is a later pass).

Reuses engine.render's game-agnostic packing/concat (pack_episodes, silence gaps,
_ffmpeg_concat -> MP3 128k, tracklist sidecars); the HZD-specific part is decoding each
clip from package.01 by (offset, length) via VGAudio.

    PYTHONPATH="src;vendor/pydecima" python -m games.hzd.render --package <pkg dir>
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from dataclasses import dataclass

from engine.render import (
    pack_episodes, budget_seconds, silence_wav, _ffmpeg_concat, format_ts,
    LINE_GAP, SCENE_GAP,
)
from engine.pack.fw_package import FwPackage
from games.hzd.atrac9 import decode_wem_to_wav, Atrac9Error

ARCHIVE = "package.01.00.core.stream"
BOUND_TIERS = {"S", "1", "2", "E"}   # E = recovered by bucket elimination (#24 mis-bind fix)


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
    a = ap.parse_args(argv)

    catalog = {r["line_id"]: r for r in _load_csv(a.catalog)}
    clip_index = {int(c["clip_row"]): c for c in _load_csv(a.clip_index)}
    if a.spine_only:
        episode_map = None
    else:
        from games.hzd.episode_map import HZD_EPISODE_MAP
        episode_map = HZD_EPISODE_MAP
    spine = build_spine(_load_csv(a.manifest), catalog, clip_index, episode_map=episode_map)
    kind = "main-quest spine" if a.spine_only else "full story reel"
    print(f"{kind}: {len(spine)} lines across {len({s.episode for s in spine})} scenes")

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)
    line_sil = silence_wav(LINE_GAP, a.cache)
    scene_sil = silence_wav(SCENE_GAP, a.cache)

    pkg = FwPackage(a.package)
    dsar = pkg.dsar_for(ARCHIVE)

    # decode each clip once (cached by clip_row); accumulate per-episode duration
    decoded, ep_secs, prev_scene_by_ep = {}, {}, {}
    import wave
    with open(a.errors, "w", encoding="utf-8") as ferr:
        for s in spine:
            wav = os.path.join(a.cache, f"{s.clip_row}.wav")
            try:
                if not (os.path.isfile(wav) and os.path.getsize(wav) > 44):
                    decode_wem_to_wav(dsar.read(s.offset, s.a_bytes), wav)
                with wave.open(wav) as w:
                    dur = w.getnframes() / float(w.getframerate())
            except (Atrac9Error, OSError, wave.Error) as e:
                ferr.write(f"{s.line_id}\t{s.clip_row}\t{e}\n")
                continue
            decoded[s.line_id] = (wav, dur)
            gap = 0.0
            if s.episode in prev_scene_by_ep:
                gap = SCENE_GAP if s.scene != prev_scene_by_ep[s.episode] else LINE_GAP
            prev_scene_by_ep[s.episode] = s.scene
            ep_secs[s.episode] = ep_secs.get(s.episode, 0.0) + gap + dur

    for fi, eps in enumerate(pack_episodes(list(ep_secs.items()), budget=budget_seconds())):
        eps_set = set(eps)
        file_segs = [s for s in spine if s.episode in eps_set and s.line_id in decoded]
        wav_list, rows, t, prev = [], [], 0.0, None
        for s in file_segs:
            wav, dur = decoded[s.line_id]
            new_scene = s.scene != prev
            if wav_list:
                wav_list.append(scene_sil if new_scene else line_sil)
                t += SCENE_GAP if new_scene else LINE_GAP
            wav_list.append(wav)
            rows.append([format_ts(t), s.scene, s.speaker, s.subtitle, s.line_id])
            t += dur
            prev = s.scene
        if not wav_list:
            continue
        stem = "hzd_mainquest" if a.spine_only else "hzd_story_reel"
        base = os.path.join(a.out_dir, f"{stem}_{fi:02d}")
        _ffmpeg_concat(wav_list, base + ".mp3", base + ".concat.txt",
                       os.path.join(a.cache, "norm"))
        with open(base + ".tracklist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "scene", "speaker", "subtitle", "line_id"])
            w.writerows(rows)
        print(f"{base}.mp3  ({len(rows)} lines, {format_ts(t)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
