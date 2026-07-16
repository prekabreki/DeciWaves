"""Phase D render: out/playlist.csv -> ~290 MB MP3 files + tracklist sidecars.

Pure packing logic here; the I/O pipeline is added next. 128 kbps CBR => bytes ~= seconds *
16000; 290 MB => 18125 s budget.

Invoke as a module (package form):
    python -m deciwaves.engine.render --data-dir <DS:DC/data> --oodle <oo2core_7_win64.dll>
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import wave
from collections import namedtuple

from deciwaves.engine.atomic_io import atomic_write

BUDGET_SECONDS = 290_000_000 * 8 / 128_000  # = 18125.0 (ideal 128 kbps, no overhead)

# Real MP3s carry ~1.1% over the ideal CBR stream (frame headers + bit
# reservoir), so packing to BUDGET_SECONDS lands files at ~293 MB -- over the
# 290 MB buffer. Callers pass budget_seconds() to target a real size.
MP3_OVERHEAD = 0.011

LINE_GAP = 0.4
SCENE_GAP = 1.5
SR = 48000


DEFAULT_BITRATE_KBPS = 128


def budget_seconds(target_mb: float = 285.0, overhead: float = MP3_OVERHEAD,
                   kbps: int = DEFAULT_BITRATE_KBPS) -> float:
    """Seconds of `kbps` CBR audio that encodes to ~`target_mb` MB once MP3
    framing overhead is included. Real bytes ~= seconds*(kbps*1000/8)*(1+overhead);
    this inverts that so a packed file lands at `target_mb`, not
    `target_mb`*(1+overhead). Default 285 MB keeps output safely under the 290 MB
    buffer. `kbps` must match the encode bitrate passed to :func:`_ffmpeg_concat` (or
    whatever `concat_fn` :func:`assemble_reels` was given, via its `concat_kwargs`),
    or packing and real file size diverge. Pass this as :func:`pack_episodes`'s or
    :func:`assemble_reels`'s `budget`, rather than mutating the shared
    :data:`BUDGET_SECONDS`."""
    return target_mb * 1_000_000 * 8 / (kbps * 1_000) / (1 + overhead)


def pack_episodes(ep_durations, budget=BUDGET_SECONDS):
    """Group whole episodes (ascending index) into files up to `budget` seconds.
    An episode longer than budget gets its own file."""
    files, cur, cur_secs = [], [], 0.0
    for ep, secs in sorted(ep_durations):
        if cur and cur_secs + secs > budget:
            files.append(cur)
            cur, cur_secs = [], 0.0
        cur.append(ep)
        cur_secs += secs
    if cur:
        files.append(cur)
    return files


_CS_GROUP_RE = re.compile(r"sq_(cs\d+)_")


def main_story_only(segs, non_story_cs_groups=frozenset()):
    """Keep only spine segments (is_side == 0). The playlist tags cutscene +
    mission as the narrative spine and everything else (prepper terminals, radio,
    allowlisted NPCs) as side content; this drops the side content for a
    main-story-only reel. Order is preserved.

    `non_story_cs_groups` additionally culls cutscene tracks whose cutscene group
    (e.g. 'cs71') is non-narrative -- DS Extra/Battlefield set-pieces, item-preview
    announcements, private-room BB chatter (see games.ds.episode_map). The cull is
    scoped to the cutscene category only. Empty set (default) = spine unchanged."""
    out = []
    for s in segs:
        if s.is_side != 0:
            continue
        if s.category == "cutscene" and non_story_cs_groups:
            m = _CS_GROUP_RE.match(s.scene)
            if m and m.group(1) in non_story_cs_groups:
                continue
        out.append(s)
    return out


def load_keepspans(path):
    """Map stream_path -> (spans, dropped) from a cutscene-keepspans.csv.
    Missing file -> {} (feature simply inactive). `spans` parsed via
    engine.speech_trim.parse_spans; `dropped` is the '1'/'0' flag."""
    import csv as _csv
    from deciwaves.engine.speech_trim import parse_spans
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            out[r["stream_path"]] = (parse_spans(r["keep_spans"]), r["dropped"] == "1")
    return out


def file_stem(main_story):
    """Output basename stem. The main-story reel gets a distinct stem so it never
    clobbers the full reel's phase_d_NN files (they share --out-dir)."""
    return "phase_d_main" if main_story else "phase_d"


def format_ts(seconds):
    s = int(seconds)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def silence_wav(seconds, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"silence_{int(seconds * 1000)}ms.wav")
    if os.path.isfile(path):
        return path

    def _run(tmp):
        with wave.open(tmp, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(b"\x00\x00\x00\x00" * int(seconds * SR))

    # atomic_write: write to a tmp path first so an interrupt mid-write can
    # never leave a truncated file at `path` that the bare isfile() check
    # above would treat as valid forever (see engine.atomic_io).
    atomic_write(path, _run)
    return path


def normalize_wav(src, norm_dir):
    """Re-encode `src` to canonical stereo / 48 kHz / s16 PCM, cached by basename.

    The ffmpeg `concat` *demuxer* requires every input to share codec, sample
    rate, channel count and sample format; it does NOT resample across segments.
    Decoded clips are a mix of mono lines and 6-channel cutscene tracks (and the
    silence gaps are stereo), so feeding them raw makes the demuxer reframe the
    odd ones out -- clips play at the wrong speed. Normalizing every input to one
    layout first keeps duration intact and makes the demuxer's output match the
    tracklist timestamps. Idempotent + cached, so re-runs are cheap.
    """
    os.makedirs(norm_dir, exist_ok=True)
    dst = os.path.join(norm_dir, os.path.basename(src))
    if os.path.isfile(dst) and os.path.getsize(dst) > 44:
        return dst

    def _run(tmp):
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-ac", "2", "-ar", str(SR),
             "-sample_fmt", "s16", tmp],
            capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.isfile(tmp):
            raise RuntimeError(f"normalize failed for {src}: {proc.stderr[-300:]}")

    # atomic_write: ffmpeg targets a tmp path, moved into place only on
    # success (see engine.atomic_io) -- an interrupted/failed normalize can
    # no longer poison the cache with a truncated file.
    atomic_write(dst, _run)
    return dst


def _ffmpeg_concat(wav_list, out_mp3, list_path, norm_dir, kbps=DEFAULT_BITRATE_KBPS):
    normed = {}
    with open(list_path, "w", encoding="utf-8") as f:
        for w in wav_list:
            nw = normed.get(w)
            if nw is None:
                nw = normalize_wav(w, norm_dir)
                normed[w] = nw
            f.write(f"file '{os.path.abspath(nw)}'\n")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
         "-b:a", f"{kbps}k", "-ac", "2", "-ar", str(SR), out_mp3],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-500:]}")


def accumulate_episode_seconds(segs, dur_of, *, gap_key, err_key, errors_path,
                               catch=Exception):
    """Decode/measure each segment in `segs`, accumulating the per-episode duration
    that :func:`pack_episodes` packs against.

    This is the "measure durations -> per-episode gap accounting" half of the render
    loop, shared across all three games: each game supplies its own `dur_of` (a Wwise
    decode for DS, an ATRAC9 decode for HZD, a bare `wave.open` read of an
    already-decoded clip for FW) and everything downstream -- gap bookkeeping, fail-soft
    error logging -- is identical.

    `dur_of(seg) -> (payload, duration_seconds)` does the game-specific decode/measure
    work. Raising anything in `catch` fails that one segment soft: logged to
    `errors_path` as ``<line_id>\\t<err_key(seg)>\\t<exc>``, then skipped -- never
    aborting the whole render.

    `gap_key(seg)` is the "same scene" key (e.g. ``lambda s: s.scene``,
    ``lambda s: s.quest``) used to price the silence gap ahead of each segment within
    its episode: SCENE_GAP when it differs from the episode's previous segment,
    LINE_GAP when it matches, 0.0 for an episode's first segment. Pass the *same*
    `gap_key` to :func:`assemble_reels` afterwards, or the packed durations won't match
    the gaps the assembly step actually inserts.

    `err_key(seg)` picks the second error-log column (DS logs `stream_path`, HZD logs
    `clip_row`, FW logs `wav`).

    Returns `(results, ep_secs, n_failed)`: `results` maps `line_id -> (payload,
    duration_seconds)` for every segment that succeeded -- this is the `durations`
    argument :func:`assemble_reels` expects; `ep_secs` maps `episode -> accumulated
    seconds` (gaps included) for :func:`pack_episodes`.
    """
    results: dict = {}
    ep_secs: dict = {}
    prev_key_by_ep: dict = {}
    n_failed = 0
    with open(errors_path, "w", encoding="utf-8") as ferr:
        for s in segs:
            try:
                payload, dur = dur_of(s)
            except catch as e:
                n_failed += 1
                ferr.write(f"{s.line_id}\t{err_key(s)}\t{e}\n")
                continue
            results[s.line_id] = (payload, dur)
            key = gap_key(s)
            if s.episode in prev_key_by_ep:
                gap = SCENE_GAP if key != prev_key_by_ep[s.episode] else LINE_GAP
            else:
                gap = 0.0
            prev_key_by_ep[s.episode] = key
            ep_secs[s.episode] = ep_secs.get(s.episode, 0.0) + gap + dur
    return results, ep_secs, n_failed


ReelColumns = namedtuple("ReelColumns", ["header", "row_of"])
"""Per-game tracklist shape for :func:`assemble_reels`.

`header`: the tracklist CSV header row (a list of column names).
`row_of(seg, timestamp_seconds) -> list`: builds one tracklist data row for a segment
at its assembled timestamp. The shape genuinely differs per game (DS ships
episode+category columns; HZD ships scene; FW ships quest), so it's supplied rather
than hardcoded.
"""


def assemble_reels(spine, ep_secs, durations, *, out_dir, cache_dir, stem, columns,
                   budget, gap_key, concat_fn=None, silence_fn=None,
                   concat_kwargs=None, unit_label="lines"):
    """Pack `spine` into <=`budget`-second reel files (:func:`pack_episodes`), splice
    each file's clips together with LINE_GAP/SCENE_GAP silence between them --
    SCENE_GAP when `gap_key(seg)` changes within an episode, matching the gaps already
    priced into `ep_secs` by :func:`accumulate_episode_seconds` -- concatenate to MP3,
    and write a `<stem>_NN.tracklist.csv` sidecar per reel.

    `durations`: `line_id -> (wav_path, duration_seconds)`, e.g. the `results` returned
    by :func:`accumulate_episode_seconds`.
    `columns`: a :data:`ReelColumns` (or plain `(header, row_of)` tuple).
    `concat_fn`/`silence_fn`: default to :func:`_ffmpeg_concat`/:func:`silence_wav`; a
    game with its own concat/silence implementation (FW's `--uniform-mono` fast path)
    passes its own instead.
    `concat_kwargs`: extra keyword arguments forwarded to `concat_fn` (e.g. DS's
    `kbps=args.bitrate`).

    Returns the number of reel files written (0 if every packed group ended up empty,
    e.g. every segment in it failed to decode).
    """
    concat_fn = concat_fn or _ffmpeg_concat
    silence_fn = silence_fn or silence_wav
    concat_kwargs = concat_kwargs or {}
    header, row_of = columns
    line_sil = silence_fn(LINE_GAP, cache_dir)
    scene_sil = silence_fn(SCENE_GAP, cache_dir)
    norm_dir = os.path.join(cache_dir, "norm")

    n_files = 0
    for fi, eps in enumerate(pack_episodes(list(ep_secs.items()), budget=budget)):
        eps_set = set(eps)
        file_segs = [s for s in spine if s.episode in eps_set and s.line_id in durations]
        wav_list, rows, t, prev = [], [], 0.0, None
        for s in file_segs:
            wav, dur = durations[s.line_id]
            key = gap_key(s)
            new_scene = key != prev
            if wav_list:
                wav_list.append(scene_sil if new_scene else line_sil)
                t += SCENE_GAP if new_scene else LINE_GAP
            wav_list.append(wav)
            rows.append(row_of(s, t))
            t += dur
            prev = key
        if not wav_list:
            continue
        base = os.path.join(out_dir, f"{stem}_{fi:02d}")
        concat_fn(wav_list, base + ".mp3", base + ".concat.txt", norm_dir, **concat_kwargs)
        with open(base + ".tracklist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        print(f"{base}.mp3  ({len(rows)} {unit_label}, {format_ts(t)})")
        n_files += 1
    return n_files


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
    args = ap.parse_args(argv)

    # imports deferred into main() (consistent with cutscene_audio.py): avoids
    # constructing PackIndex at module import time; keeps `import engine.render` test-clean
    from deciwaves.engine import audio_clip
    from deciwaves.engine import story_order
    from deciwaves.engine.pack.bin_index import PackIndex
    from deciwaves.games.ds import episode_map as em

    idx = PackIndex(args.data_dir, args.oodle)
    os.makedirs(args.out_dir, exist_ok=True)
    segs = story_order.read_playlist(args.playlist)
    if args.main_story:
        kept = main_story_only(segs, non_story_cs_groups=em.NON_STORY_CS_GROUPS)
        print(f"main-story filter: kept {len(kept)}/{len(segs)} segments "
              f"(dropped {len(segs) - len(kept)} side + non-story cutscene groups "
              f"{sorted(em.NON_STORY_CS_GROUPS)})")
        segs = kept
    stem = file_stem(args.main_story)

    keepspans = load_keepspans(args.speech_trim) if args.speech_trim else {}
    if keepspans:
        n_drop = sum(1 for s in segs if keepspans.get(s.stream_path, (None, False))[1])
        print(f"speech-trim: {len(keepspans)} tracks in map; {n_drop} segments will be dropped")

    # dropped pure-grunt tracks (speech-trim) never even get attempted -- filter them
    # out before decoding so n_attempted below matches the original per-clip accounting.
    decode_segs = [s for s in segs
                   if not (keepspans.get(s.stream_path) and keepspans[s.stream_path][1])]
    n_attempted = len(decode_segs)

    def _decode(s):
        entry = keepspans.get(s.stream_path)
        wav, dur = audio_clip.clip_wav(idx, s.stream_path, args.cache)
        if entry:                             # keep-span trim (cutscene)
            wav, dur = audio_clip.apply_keep_spans(
                wav, entry[0], os.path.join(args.cache, "kept"))
        elif args.min_silence > 0:            # unchanged silencedetect path
            wav, dur = audio_clip.trim_long_silences(
                wav, os.path.join(args.cache, "trimmed"),
                min_silence=args.min_silence, threshold_db=args.silence_db,
                keep=args.silence_keep)
        return wav, dur

    decoded, ep_secs, n_failed = accumulate_episode_seconds(
        decode_segs, _decode, gap_key=lambda s: s.scene, err_key=lambda s: s.stream_path,
        errors_path=args.errors, catch=audio_clip.ClipError)

    n_decoded = len(decoded)
    print(f"render: decoded {n_decoded} clips, {n_failed} failed (see {args.errors})")
    if n_decoded == 0 and n_attempted > 0:
        print(f"render: ERROR - no audio could be decoded out of {n_attempted} "
              f"segment(s) attempted. See {args.errors} for the per-clip failures. "
              f"Try `deciwaves doctor` to check your decode tools, and see the "
              f"README's Windows Store Python troubleshooting note if vgmstream-cli "
              f"is dying with a DLL-not-found / exit-code error.")
        return 1

    columns = ReelColumns(
        header=["timestamp", "episode", "category", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.episode, s.category, s.speaker, s.subtitle,
                             s.line_id])
    assemble_reels(
        segs, ep_secs, decoded, out_dir=args.out_dir, cache_dir=args.cache, stem=stem,
        columns=columns, budget=budget_seconds(kbps=args.bitrate),
        gap_key=lambda s: s.scene, concat_kwargs={"kbps": args.bitrate},
        unit_label="segments")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
