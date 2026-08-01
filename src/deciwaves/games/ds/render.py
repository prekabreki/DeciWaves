"""DS render: story-ordered playlist -> MP3 reels.

Packs the playlist into <=290 MB MP3 files, inserting silence gaps between lines
and scenes, and writes a tracklist CSV alongside each MP3. Decodes clips from the
PackIndex via vgmstream-cli; speech-trim keep-spans optional.

Invoke as a module (package form):
    python -m deciwaves.games.ds.render --data-dir <DS:DC/data> --oodle <oo2core_7_win64.dll>
"""
from __future__ import annotations

import csv
import os
import re

from deciwaves.engine.render import (
    accumulate_episode_seconds, assemble_reels, budget_seconds, finish_render,
    ReelColumns, DEFAULT_BITRATE_KBPS, format_ts,
)
from deciwaves.engine.parallel import default_jobs

_CS_GROUP_RE = re.compile(r"sq_(cs\d+)_")


def _cs_group_of(scene):
    m = _CS_GROUP_RE.match(scene)
    return m.group(1) if m else None


def main_story_only(segs, non_story_cs_groups=frozenset(), group_of=_cs_group_of):
    """Keep only spine segments (is_side == 0). The playlist tags cutscene +
    mission as the narrative spine and everything else (prepper terminals, radio,
    allowlisted NPCs) as side content; this drops the side content for a
    main-story-only reel. Order is preserved.

    `non_story_cs_groups` additionally culls cutscene tracks whose cutscene group
    (e.g. 'cs71') is non-narrative -- DS Extra/Battlefield set-pieces, item-preview
    announcements, private-room BB chatter (see games.ds.episode_map). The cull is
    scoped to the cutscene category only. Empty set (default) = spine unchanged.

    `group_of(scene) -> group_id | None` resolves a scene string to its cutscene
    group; defaults to this module's own `_CS_GROUP_RE` (identical to
    `games.ds.episode_map.cs_group`) so a caller with its own group-resolution
    logic (e.g. DS's own `episode_map.cs_group`) can pass it in instead of this
    module keeping a second, independently-maintained copy of the same regex."""
    out = []
    for s in segs:
        if s.is_side != 0:
            continue
        if s.category == "cutscene" and non_story_cs_groups:
            g = group_of(s.scene)
            if g is not None and g in non_story_cs_groups:
                continue
        out.append(s)
    return out


def load_keepspans(path):
    """Map stream_path -> (spans, dropped) from a cutscene-keepspans.csv.
    Missing file -> {} (feature simply inactive). `spans` parsed via
    games.ds.speech_trim.parse_spans; `dropped` is the '1'/'0' flag."""
    from deciwaves.games.ds.speech_trim import parse_spans
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["stream_path"]] = (parse_spans(r["keep_spans"]), r["dropped"] == "1")
    return out


def file_stem(main_story):
    """Output basename stem. The main-story reel gets a distinct stem so it never
    clobbers the full reel's phase_d_NN files (they share --out-dir)."""
    return "phase_d_main" if main_story else "phase_d"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Render Phase D story audio")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--playlist", default="out/playlist.csv")
    ap.add_argument("--out-dir", default="out/audio")
    ap.add_argument("--cache", default="out/wav-cache")
    ap.add_argument("--errors", default="out/render-errors.log")
    ap.add_argument("--min-silence", type=float, default=10.0,
                    help="collapse silences >= this many seconds (0 disables trimming)")
    ap.add_argument("--silence-db", type=float, default=-30.0,
                    help="silence threshold in dBFS (-30 also catches quiet "
                         "ambient/breathing-level dead air, not just true silence)")
    ap.add_argument("--silence-keep", type=float, default=0.75,
                    help="seconds of each long silence to keep")
    ap.add_argument("--main-story", action="store_true",
                    help="render only the narrative spine (cutscene + mission, "
                         "is_side==0); writes phase_d_main_NN instead of phase_d_NN")
    ap.add_argument("--speech-trim", default="",
                    help="path to cutscene-keepspans.csv: trim cutscene tracks "
                         "to spoken regions; drop pure-grunt tracks. Empty = disabled")
    ap.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE_KBPS,
                    help="MP3 CBR bitrate in kbps (drives both encode and the "
                         "byte-budget packing math). Lower = fewer files; speech is "
                         "highly compressible so ~96 stays ~transparent")
    ap.add_argument("--target-mb", type=float, default=285.0,
                    help="Target MB per reel file (default 285; output stays safely "
                         "under the 290 MB buffer)")
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="number of clips to decode concurrently (each spawns one "
                         f"vgmstream-cli). Default min(8, cpu_count)={default_jobs()}; "
                         "--jobs 1 forces the old serial decode")
    args = ap.parse_args(argv)

    # imports deferred into main() (consistent with cutscene_audio.py): avoids
    # constructing PackIndex at module import time; keeps `import games.ds.render` test-clean
    from deciwaves.engine import audio_clip
    from deciwaves.engine.tool_paths import resolve
    from deciwaves.games.ds import story_order
    from deciwaves.engine.pack.bin_index import PackIndex
    from deciwaves.games.ds import episode_map as em

    vgmstream = resolve("DECIWAVES_VGMSTREAM", "vgmstream-cli")

    idx = PackIndex(args.data_dir, args.oodle)
    os.makedirs(args.out_dir, exist_ok=True)
    try:
        rows = story_order.read_playlist(args.playlist)
    except FileNotFoundError:
        # Running render before order (issue #311): a missing playlist is an
        # "upstream produced nothing" failure, not a traceback.
        print(f"render: ERROR - {args.playlist} does not exist -- run "
              f"`deciwaves ds order` to create it first.")
        return 1
    n_rows = len(rows)
    if args.main_story:
        kept = main_story_only(rows, non_story_cs_groups=em.NON_STORY_CS_GROUPS,
                               group_of=em.cs_group)
        print(f"main-story filter: kept {len(kept)}/{n_rows} segments "
              f"(dropped {n_rows - len(kept)} side + non-story cutscene groups "
              f"{sorted(em.NON_STORY_CS_GROUPS)})")
        rows = kept
    stem = file_stem(args.main_story)

    if args.speech_trim and not os.path.isfile(args.speech_trim):
        print(f"render: --speech-trim path not found: {args.speech_trim} "
              f"(pass a real cutscene-keepspans.csv, or omit --speech-trim to "
              f"disable trimming)")
        return 1
    keepspans = load_keepspans(args.speech_trim) if args.speech_trim else {}
    if keepspans:
        n_drop = sum(1 for s in rows if keepspans.get(s.stream_path, (None, False))[1])
        print(f"speech-trim: {len(keepspans)} tracks in map; {n_drop} segments will be dropped")

    decode_segs = [s for s in rows
                   if not (keepspans.get(s.stream_path) and keepspans[s.stream_path][1])]

    def _decode(s):
        entry = keepspans.get(s.stream_path)
        wav, dur = audio_clip.clip_wav(idx, s.stream_path, args.cache, vgmstream=vgmstream)
        if entry:
            wav, dur = audio_clip.apply_keep_spans(
                wav, entry[0], os.path.join(args.cache, "kept"))
        elif args.min_silence > 0:
            wav, dur = audio_clip.trim_long_silences(
                wav, os.path.join(args.cache, "trimmed"),
                min_silence=args.min_silence, threshold_db=args.silence_db,
                keep=args.silence_keep)
        return wav, dur

    decoded, ep_secs, n_failed = {}, {}, 0
    if decode_segs:
        decoded, ep_secs, n_failed = accumulate_episode_seconds(
            decode_segs, _decode, gap_key=lambda s: s.scene, err_key=lambda s: s.stream_path,
            errors_path=args.errors, catch=audio_clip.ClipError, jobs=args.jobs)
        print(f"render: decoded {len(decoded)} clips, {n_failed} failed (see {args.errors})")

    columns = ReelColumns(
        header=["timestamp", "episode", "category", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.episode, s.category, s.speaker, s.subtitle,
                             s.line_id])
    return finish_render(
        decode_segs, n_rows == 0, args.errors,
        msg_empty_input=(
            f"render: ERROR - {args.playlist} has no rows -- upstream "
            f"produced no lines to render. Re-run `deciwaves ds order`; "
            f"no reels written to {args.out_dir}."
        ),
        msg_empty_selection=(
            f"render: nothing to render: none of the {n_rows} rows in "
            f"{args.playlist} survived the --main-story / --speech-trim "
            f"filters -- no reels written to {args.out_dir}."
        ),
        msg_nothing_decoded=(
            f"render: ERROR - no audio could be decoded out of "
            f"{len(decode_segs)} segment(s) attempted. See {args.errors} for "
            f"the per-clip failures. Try `deciwaves doctor` to check your "
            f"decode tools, and see the README's Windows Store Python "
            f"troubleshooting note if vgmstream-cli is dying with a "
            f"DLL-not-found / exit-code error."
        ),
        msg_zero_files=(
            f"render: ERROR - 0 reel files written to {args.out_dir} from "
            f"{len(decode_segs)} spine segments -- see {args.errors}."
        ),
        durations=decoded, ep_secs=ep_secs,
        out_dir=args.out_dir, cache_dir=args.cache, stem=stem, columns=columns,
        budget=budget_seconds(target_mb=args.target_mb, kbps=args.bitrate),
        gap_key=lambda s: s.scene,
        _assemble=assemble_reels, concat_kwargs={"kbps": args.bitrate},
        unit_label="segments")


if __name__ == "__main__":
    import sys
    sys.exit(main())
