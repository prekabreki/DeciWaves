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
    buffer. `kbps` must match the encode bitrate passed to :func:`_ffmpeg_concat`,
    or packing and real file size diverge. Pass this to :func:`pack_episodes`
    rather than mutating the shared :data:`BUDGET_SECONDS`."""
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
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"\x00\x00\x00\x00" * int(seconds * SR))
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
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ac", "2", "-ar", str(SR),
         "-sample_fmt", "s16", dst],
        capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(dst):
        raise RuntimeError(f"normalize failed for {src}: {proc.stderr[-300:]}")
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
    line_sil = silence_wav(LINE_GAP, args.cache)
    scene_sil = silence_wav(SCENE_GAP, args.cache)

    keepspans = load_keepspans(args.speech_trim) if args.speech_trim else {}
    if keepspans:
        n_drop = sum(1 for s in segs if keepspans.get(s.stream_path, (None, False))[1])
        print(f"speech-trim: {len(keepspans)} tracks in map; {n_drop} segments will be dropped")

    decoded, ep_secs = {}, {}
    prev_scene_by_ep = {}
    n_attempted = n_failed = 0
    with open(args.errors, "w", encoding="utf-8") as ferr:
        for s in segs:
            entry = keepspans.get(s.stream_path)
            if entry and entry[1]:                    # dropped pure-grunt track
                continue
            n_attempted += 1
            try:
                wav, dur = audio_clip.clip_wav(idx, s.stream_path, args.cache)
                if entry:                             # keep-span trim (cutscene)
                    wav, dur = audio_clip.apply_keep_spans(
                        wav, entry[0], os.path.join(args.cache, "kept"))
                elif args.min_silence > 0:            # unchanged silencedetect path
                    wav, dur = audio_clip.trim_long_silences(
                        wav, os.path.join(args.cache, "trimmed"),
                        min_silence=args.min_silence, threshold_db=args.silence_db,
                        keep=args.silence_keep)
            except audio_clip.ClipError as e:
                n_failed += 1
                ferr.write(f"{s.line_id}\t{s.stream_path}\t{e}\n"); continue
            decoded[s.line_id] = (wav, dur)
            if s.episode in prev_scene_by_ep:
                gap = SCENE_GAP if s.scene != prev_scene_by_ep[s.episode] else LINE_GAP
            else:
                gap = 0.0
            prev_scene_by_ep[s.episode] = s.scene
            ep_secs[s.episode] = ep_secs.get(s.episode, 0.0) + gap + dur

    n_decoded = len(decoded)
    print(f"render: decoded {n_decoded} clips, {n_failed} failed (see {args.errors})")
    if n_decoded == 0 and n_attempted > 0:
        print(f"render: ERROR - no audio could be decoded out of {n_attempted} "
              f"segment(s) attempted. See {args.errors} for the per-clip failures. "
              f"Try `deciwaves doctor` to check your decode tools, and see the "
              f"README's Windows Store Python troubleshooting note if vgmstream-cli "
              f"is dying with a DLL-not-found / exit-code error.")
        return 1

    for fi, eps in enumerate(pack_episodes(list(ep_secs.items()),
                                           budget=budget_seconds(kbps=args.bitrate))):
        eps_set = set(eps)
        file_segs = [s for s in segs if s.episode in eps_set and s.line_id in decoded]
        wav_list, rows, t, prev = [], [], 0.0, None
        for s in file_segs:
            wav, dur = decoded[s.line_id]
            new_scene = s.scene != prev
            if wav_list:
                wav_list.append(scene_sil if new_scene else line_sil)
                t += SCENE_GAP if new_scene else LINE_GAP
            wav_list.append(wav)
            rows.append([format_ts(t), s.episode, s.category, s.speaker, s.subtitle, s.line_id])
            t += dur
            prev = s.scene
        if not wav_list:
            continue
        base = os.path.join(args.out_dir, f"{stem}_{fi:02d}")
        _ffmpeg_concat(wav_list, base + ".mp3", base + ".concat.txt",
                       os.path.join(args.cache, "norm"), kbps=args.bitrate)
        with open(base + ".tracklist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "episode", "category", "speaker", "subtitle", "line_id"])
            w.writerows(rows)
        print(f"{base}.mp3  ({len(rows)} segments, {format_ts(t)})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
