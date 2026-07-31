"""Game-agnostic render assembly kit.

Pure packing logic and the measure-durations -> gap-accounting -> pack -> concat ->
tracklist loop, shared across all three games. Each game supplies its own clip
decode (`dur_of`) and tracklist column shape (`ReelColumns`); the gap bookkeeping,
packing, and assembly are identical.
"""
from __future__ import annotations

import csv
import os
import subprocess
import wave
from collections import namedtuple

from deciwaves.engine.atomic_io import atomic_write
from deciwaves.engine.parallel import ordered_parallel

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
                               catch=Exception, jobs=1):
    """Decode/measure each segment in `segs`, accumulating the per-episode duration
    that :func:`pack_episodes` packs against.

    This is the "measure durations -> per-episode gap accounting" half of the render
    loop, shared across all three games: each game supplies its own `dur_of` (a Wwise
    decode for DS, an ATRAC9 decode for HZD, a bare `wave.open` read of an
    already-decoded clip for FW) and everything downstream -- gap bookkeeping, fail-soft
    error logging -- is identical.

    `dur_of(seg) -> (payload, duration_seconds)` does the game-specific decode/measure
    work. Raising anything in `catch` fails that one segment soft: logged to
    `errors_path` as ``<line_id>\\t<err_key(seg)>\\t<exc type name>: <exc>``, then
    skipped -- never aborting the whole render.

    `gap_key(seg)` is the "same scene" key (e.g. ``lambda s: s.scene``,
    ``lambda s: s.quest``) used to price the silence gap ahead of each segment within
    its episode: SCENE_GAP when it differs from the episode's previous segment,
    LINE_GAP when it matches, 0.0 for an episode's first segment. Pass the *same*
    `gap_key` to :func:`assemble_reels` afterwards, or the packed durations won't match
    the gaps the assembly step actually inserts.

    `err_key(seg)` picks the second error-log column (DS logs `stream_path`, HZD logs
    `clip_row`, FW logs `wav`).

    `jobs` runs the (subprocess-bound) `dur_of` calls in a worker pool of that size
    (see :func:`engine.parallel.ordered_parallel`); ``jobs=1`` (default) runs them
    inline, exactly the old serial loop. Only `dur_of` is parallelized: the gap
    accounting, the `results`/`ep_secs` mutation and every write to `errors_path` all
    happen on the calling thread, in segment order, so the output is byte-identical to
    the serial run and needs no lock. A `dur_of` failure outside `catch` still aborts,
    at the same segment the serial loop would have raised on.

    Returns `(results, ep_secs, n_failed)`: `results` maps `line_id -> (payload,
    duration_seconds)` for every segment that succeeded -- this is the `durations`
    argument :func:`assemble_reels` expects; `ep_secs` maps `episode -> accumulated
    seconds` (gaps included) for :func:`pack_episodes`.
    """
    results: dict = {}
    ep_secs: dict = {}
    prev_key_by_ep: dict = {}
    n_failed = 0

    def _measure(s):
        try:
            return s, dur_of(s), None
        except Exception as e:  # noqa: BLE001 - re-classified against `catch` below
            return s, None, e

    with open(errors_path, "w", encoding="utf-8") as ferr:
        for s, payload_dur, exc in ordered_parallel(segs, _measure, jobs):
            if exc is not None:
                if not isinstance(exc, catch):
                    raise exc
                n_failed += 1
                ferr.write(f"{s.line_id}\t{err_key(s)}\t{type(exc).__name__}: {exc}\n")
                continue
            payload, dur = payload_dur
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


def finish_render(spine, empty_input, errors_path,
                    msg_empty_input, msg_empty_selection,
                    msg_nothing_decoded, msg_zero_files,
                    durations, ep_secs, out_dir, cache_dir, stem, columns, budget, gap_key,
                    _assemble=assemble_reels,
                    **assemble_kwargs):
    """Shared exit-code contract tail for HZD and FW render ``main()`` functions.

    Consolidates the empty-state / exit-code bookkeeping that was verbatim-duplicated
    across ``games/hzd/render.py`` and ``games/fw/render.py`` (#231). Every branch
    preserves the precise rc contract ``run`` / the GUI stage strip trust (#64/#85):

    * **Empty spine** (``not spine``): drops a stale *errors_path* from a prior run
      (decode/measure -- its only writer -- never runs on either branch below, so a
      leftover log would otherwise be misread as this run's failures). Then:

        * **Empty INPUT** (``empty_input`` is True, meaning a header-only manifest):
          rc 1, loud -- an upstream stage produced nothing, not a deliberate selection.
        * **Empty SELECTION** (rows present, none bound/in-scope): rc 0, no-op -- a
          legitimate narrowing (e.g. ``--spine-only`` with only side scenes bound, or
          ``--tiers D`` against the standard full-reel manifest).

    * **Nothing decoded** (``not durations``): rc 1 -- ``spine`` is known non-empty
      (the no-op case returned above), so zero successful decodes/measurements is a
      decode-toolchain failure, not a zero-clip "success" (#64).

    * **Zero reel files** (``assemble_reels`` returns 0): rc 1 -- defensive backstop
      (#64). With the ``not durations`` guard above a non-empty ``durations`` always
      packs >=1 reel, so this is unreachable today; kept as a cheap honest-exit-code
      guard in case ``assemble_reels``' contract ever changes, since ``run``/the
      GUI trust this stage's rc.

    Game-specific message strings (``msg_*``) are supplied by each caller; the control
    flow is identical. ``_assemble`` defaults to this module's :func:`assemble_reels`;
    callers that need testability pass their own import of it (so a monkeypatch on
    the caller's namespace intercepts the call). ``**assemble_kwargs`` is forwarded
    to ``_assemble`` (e.g. ``concat_fn``, ``silence_fn``, ``concat_kwargs``).
    """
    if not spine:
        try:
            os.remove(errors_path)
        except OSError:
            pass
        if empty_input:
            print(msg_empty_input)
            return 1
        print(msg_empty_selection)
        return 0
    if not durations:
        print(msg_nothing_decoded)
        return 1
    n_files = _assemble(
        spine, ep_secs, durations, out_dir=out_dir, cache_dir=cache_dir,
        stem=stem, columns=columns, budget=budget, gap_key=gap_key,
        **assemble_kwargs)
    if n_files == 0:
        print(msg_zero_files)
        return 1
    return 0
