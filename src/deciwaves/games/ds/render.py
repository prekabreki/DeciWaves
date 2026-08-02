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
    accumulate_episode_seconds, assemble_reels, assemble_single_file,
    budget_seconds, finish_render, finish_single_file,
    ReelColumns, DEFAULT_BITRATE_KBPS, format_ts,
)
from deciwaves.engine.parallel import default_jobs

_CS_GROUP_RE = re.compile(r"sq_(cs\d+)_")

# Decode-failure thresholds (issue #411). Per-clip decoding is deliberately fail-soft
# so a few bad streams can't abort a multi-hour render -- but without a threshold the
# run reports success at ANY failure rate. A real render once failed 3,593 of 5,439
# clips (66%), printed a plausible duration and size, and exited 0.
DECODE_WARN_FRACTION = 0.10
DECODE_FAIL_FRACTION = 0.50
# A fraction alone is meaningless at small N: 1 failure out of 2 clips is noise,
# 3,593 out of 5,439 is a broken run. Below this many attempted clips the per-clip
# summary line is the only signal, and partial success stays rc 0 as it always has.
DECODE_MIN_ATTEMPTED = 20


def _failure_fraction(n_decoded, n_failed):
    """(attempted, fraction) or (attempted, None) when the sample is too small to judge."""
    attempted = n_decoded + n_failed
    if not n_failed or attempted < DECODE_MIN_ATTEMPTED:
        return attempted, None
    return attempted, n_failed / attempted


def decode_failure_rc(rc, n_decoded, n_failed, errors_path):
    """Escalate `rc` to 1 when decode failures exceed DECODE_FAIL_FRACTION.

    The denominator is clips *attempted* (decoded + failed), NOT playlist rows --
    segments dropped upstream by the selection or speech-trim filters were never
    attempted and are not failures.
    """
    attempted, frac = _failure_fraction(n_decoded, n_failed)
    if frac is None:
        return rc
    if frac >= DECODE_FAIL_FRACTION:
        print(f"render: ERROR - {n_failed}/{attempted} clips ({frac:.0%}) failed to "
              f"decode. This is not a successful render; see {errors_path}.")
        return rc or 1
    return rc


def warn_decode_failures(n_decoded, n_failed, errors_path):
    """Print a marked warning when failures exceed DECODE_WARN_FRACTION."""
    attempted, frac = _failure_fraction(n_decoded, n_failed)
    if frac is not None and frac >= DECODE_WARN_FRACTION:
        print(f"render: WARNING - {n_failed}/{attempted} clips ({frac:.0%}) failed "
              f"to decode; the output is missing that audio. See {errors_path}.")


def _cs_group_of(scene):
    m = _CS_GROUP_RE.match(scene)
    return m.group(1) if m else None


def is_story(seg, non_story_cs_groups=frozenset(), group_of=_cs_group_of):
    """True when `seg` is narrative ("story") audio: ``is_side == 0`` and, for
    a cutscene track, not a non-story cutscene group.

    Per-segment form of :func:`main_story_only` (which is exactly this applied
    to a list) -- the story/filler predicate DS supplies to deliverable 1
    (`--single-file`). The playlist tags cutscene + mission as the narrative
    spine and everything else (prepper terminals, radio, allowlisted NPCs) as
    side content.

    `non_story_cs_groups` additionally culls cutscene tracks whose cutscene
    group (e.g. 'cs71') is non-narrative -- DS Extra/Battlefield set-pieces,
    item-preview announcements, private-room BB chatter (see
    games.ds.episode_map). The cull is scoped to the cutscene category only.
    Empty set (default) = spine unchanged.

    `group_of(scene) -> group_id | None` resolves a scene string to its
    cutscene group; defaults to this module's own `_CS_GROUP_RE` (identical to
    `games.ds.episode_map.cs_group`)."""
    if seg.is_side != 0:
        return False
    if seg.category == "cutscene" and non_story_cs_groups:
        g = group_of(seg.scene)
        if g is not None and g in non_story_cs_groups:
            return False
    return True


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
    return [s for s in segs if is_story(s, non_story_cs_groups, group_of)]


def load_keepspans(path):
    """Map stream_path -> (spans, dropped) from a cutscene-keepspans.csv.
    Missing file -> {} (feature simply inactive). `spans` parsed via
    games.ds.speech_trim.parse_spans; `dropped` is the '1'/'0' flag."""
    from deciwaves.games.ds.speech_trim import parse_spans
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
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
    ap.add_argument("--single-file", action="store_true",
                    help="render ONE story-only MP3 (deliverable 1): drops "
                         "filler, auto-picks the highest standard MP3 bitrate "
                         "that fits --target-mb, and prints the chosen kbps + "
                         "predicted size before encoding (ignores --bitrate)")
    ap.add_argument("--speech-trim", default=None,
                    help="path to cutscene-keepspans.csv: trim cutscene tracks "
                         "to spoken regions; drop pure-grunt tracks. Omit = use the "
                         "packaged ds/cutscene-keepspans.csv; pass '' to disable")
    ap.add_argument("--curated", action="store_true",
                    help="the playlist IS the selection: render its rows verbatim, "
                         "skipping the is_side / non-story-cutscene filters. For "
                         "externally curated playlists whose row order and membership "
                         "are authoritative (silence trimming still applies)")
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
    if args.curated:
        # The curated playlist IS the selection -- an external pass already decided
        # membership and order, so re-applying is_side / non-story-cutscene culls here
        # would silently discard deliberately-kept material (issue #406).
        print(f"curated: rendering all {n_rows} playlist rows verbatim "
              f"(selection filters skipped)")
    if args.main_story and not args.curated:
        kept = main_story_only(rows, non_story_cs_groups=em.NON_STORY_CS_GROUPS,
                               group_of=em.cs_group)
        print(f"main-story filter: kept {len(kept)}/{n_rows} segments "
              f"(dropped {n_rows - len(kept)} side + non-story cutscene groups "
              f"{sorted(em.NON_STORY_CS_GROUPS)})")
        rows = kept
    if args.single_file and not args.curated:
        # Deliverable 1 is story-only: drop filler BEFORE decode so the decode
        # budget isn't spent on lines that can't ship. Zero story lines is a
        # failure (rc 1), not a 0-byte no-op -- and drops a stale errors log
        # since measure (its only writer) never runs on this branch.
        kept = main_story_only(rows, non_story_cs_groups=em.NON_STORY_CS_GROUPS,
                               group_of=em.cs_group)
        print(f"single-file story filter: kept {len(kept)}/{n_rows} segments "
              f"(dropped {n_rows - len(kept)} filler)")
        if n_rows and not kept:
            try:
                os.remove(args.errors)
            except OSError:
                pass
            print(f"render: ERROR - none of the {n_rows} rows in "
                  f"{args.playlist} is story (is_side == 0). Deliverable 1 "
                  f"renders the narrative spine only; no file written to "
                  f"{args.out_dir}.")
            return 1
        rows = kept
    stem = file_stem(args.main_story or args.single_file)

    # `None` (flag omitted) -> the packaged keepspans; `""` -> explicitly disabled.
    # This MUST stay an `is None` test: "" is falsy, so `args.speech_trim or packaged()`
    # would swallow the explicit-disable case and look correct (issue #408). Omitting the
    # trim on DS costs ~51 minutes of pure dead air, because DS cutscenes are whole-scene
    # tracks that play their non-speech gameplay audio in full.
    speech_trim, trim_source = args.speech_trim, "explicit"
    if speech_trim is None:
        from deciwaves import data
        try:
            speech_trim, trim_source = str(data.packaged("ds/cutscene-keepspans.csv")), "packaged default"
        except FileNotFoundError:
            speech_trim = ""
            print("render: WARNING - ds/cutscene-keepspans.csv isn't bundled in this "
                  "build, so cutscenes will render UNTRIMMED, including their "
                  "non-speech gameplay audio. Pass --speech-trim <path> to fix.")
    if speech_trim and not os.path.isfile(speech_trim):
        print(f"render: --speech-trim path not found: {speech_trim} "
              f"(pass a real cutscene-keepspans.csv, or pass --speech-trim '' to "
              f"disable trimming)")
        return 1
    keepspans = load_keepspans(speech_trim) if speech_trim else {}
    if keepspans:
        n_drop = sum(1 for s in rows if keepspans.get(s.stream_path, (None, False))[1])
        print(f"speech-trim: {len(keepspans)} tracks in map ({trim_source}); "
              f"{n_drop} segments will be dropped")

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
        warn_decode_failures(len(decoded), n_failed, args.errors)

    columns = ReelColumns(
        header=["timestamp", "episode", "category", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.episode, s.category, s.speaker, s.subtitle,
                             s.line_id])
    if args.single_file:
        rc = finish_single_file(
            decode_segs, n_rows == 0, args.errors,
            msg_empty_input=(
                f"render: ERROR - {args.playlist} has no rows -- upstream "
                f"produced no lines to render. Re-run `deciwaves ds order`; "
                f"no file written to {args.out_dir}."
            ),
            msg_empty_selection=(
                f"render: nothing to render: none of the {n_rows} rows in "
                f"{args.playlist} survived the --single-file / --main-story / "
                f"--speech-trim filters -- no file written to {args.out_dir}."
            ),
            msg_nothing_decoded=(
                f"render: ERROR - no audio could be decoded out of "
                f"{len(decode_segs)} segment(s) attempted. See {args.errors} for "
                f"the per-clip failures. Try `deciwaves doctor` to check your "
                f"decode tools, and see the README's Windows Store Python "
                f"troubleshooting note if vgmstream-cli is dying with a "
                f"DLL-not-found / exit-code error."
            ),
            msg_zero_story=(
                f"render: ERROR - none of the {len(decode_segs)} segment(s) in "
                f"{args.playlist} is story (is_side == 0). Deliverable 1 renders "
                f"the narrative spine only; no file written to {args.out_dir}."
            ),
            durations=decoded,
            out_dir=args.out_dir, cache_dir=args.cache, stem=stem, columns=columns,
            gap_key=lambda s: s.scene,
            # --curated: the playlist is authoritative, so every row is "story" here.
            # finish_single_file applies this predicate a SECOND time, after the
            # pre-decode filter above -- both must be neutralised (issue #406).
            story_predicate=((lambda s: True) if args.curated else (lambda s: is_story(
                s, em.NON_STORY_CS_GROUPS, em.cs_group))),
            _assemble=assemble_single_file, unit_label="segments")
        return decode_failure_rc(rc, len(decoded), n_failed, args.errors)
    rc = finish_render(
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
    return decode_failure_rc(rc, len(decoded), n_failed, args.errors)


if __name__ == "__main__":
    import sys
    sys.exit(main())
