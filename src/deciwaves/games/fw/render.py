"""FW render (final stage): labeled manifest -> story-ordered MP3 reel(s).

Simpler than the HZD render: the clip WAVs already exist (`out/fw/audio/`, from
the fast-path extractor), so there is NO decode step — order the bound lines by `gamescript_index`
(rough chronological; the gamescript already interleaves main/side/DLC), measure,
pack to <=290 MB MP3s, and concat with gaps. Reuses the game-agnostic assembly kit
(accumulate_episode_seconds, assemble_reels) from `engine.render`.

    PYTHONPATH=src python -m deciwaves.games.fw.render
"""

from __future__ import annotations

import argparse
import os
import wave

import subprocess

from deciwaves.engine.catalog_io import read_csv_rows, CsvFormatError
from deciwaves.engine.render import (
    SR, DEFAULT_BITRATE_KBPS, accumulate_episode_seconds, assemble_reels,
    assemble_single_file, budget_seconds, finish_render, finish_single_file,
    format_ts, ReelColumns,
)
from deciwaves.engine.render_spine import BOUND_TIERS, RenderItem, build_spine, REQUIRED_COLS  # noqa: F401

# Default --manifest: the full-reel stage (story_full.py)'s own default --out.
# Keep these in lockstep -- see test_render_default_manifest_matches_full_reel_stage_output.
DEFAULT_MANIFEST = "out/fw/full-reel-manifest.csv"
# Default --tiers: every tier the full-reel manifest actually ships, INCLUDING
# "S" (subtitle-only, no gamescript match) -- that's most of the full reel's
# lines; dropping it silently would defeat the point of the full-reel deliverable.
DEFAULT_TIERS = "1,2,S"
MONO_FMT = (1, SR, 2)        # FW fast-path clips are all mono / 48 kHz / s16


def mono_silence_wav(seconds, cache_dir):
    """Mono 48 kHz s16 silence, matching the FW clip format (for the fast concat)."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"silence_mono_{int(seconds * 1000)}ms.wav")
    if os.path.isfile(path):
        return path
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"\x00\x00" * int(seconds * SR))
    return path


def _is_mono(wav):
    try:
        with wave.open(wav) as w:
            return (w.getnchannels(), w.getframerate(), w.getsampwidth()) == MONO_FMT
    except (wave.Error, OSError, EOFError):
        return False


def _concat_uniform(wav_list, out_mp3, list_path, norm_dir, kbps=DEFAULT_BITRATE_KBPS):
    """Concat clips that are already uniform mono/48k/s16 with NO per-file re-encode.

    Skips the normalize step that would copy tens of GB at bulk scale; only the rare
    non-conforming clip is normalized (to mono). Inputs must already share format.
    """
    os.makedirs(norm_dir, exist_ok=True)
    fixed = {}
    with open(list_path, "w", encoding="utf-8") as f:
        for w in wav_list:
            if _is_mono(w):
                use = w
            elif w in fixed:
                use = fixed[w]
            else:
                dst = os.path.join(norm_dir, os.path.basename(w))
                subprocess.run(["ffmpeg", "-y", "-i", w, "-ac", "1", "-ar", str(SR),
                                "-sample_fmt", "s16", dst], capture_output=True, text=True)
                use = fixed[w] = dst
            f.write(f"file '{os.path.abspath(use)}'\n")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
         "-b:a", f"{kbps}k", "-ac", "1", "-ar", str(SR), out_mp3],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-500:]}")


def is_story(item):
    """Story/filler split for FW (deliverable 1): a line is 'story' when it is
    bound to the gamescript -- non-empty `speaker`. The full-reel manifest's
    tier-S rows are exact-subtitle-only lines with no gamescript match (empty
    speaker); they are filler for the story-only single-file deliverable."""
    return bool((item.speaker or "").strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render FW story reel to MP3")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--audio-root", default="out/fw",
                    help="dir the manifest 'wav' paths are relative to")
    ap.add_argument("--out-dir", default="out/fw/reels")
    ap.add_argument("--cache", default="out/fw/wav-cache")
    ap.add_argument("--errors", default="out/fw/render-errors.log")
    ap.add_argument("--tiers", default=DEFAULT_TIERS,
                    help="comma-separated tiers to ship (e.g. '1' confident-only, 'D' for DLC)")
    ap.add_argument("--stem", default="fw_story_reel", help="output MP3 filename stem")
    ap.add_argument("--single-file", action="store_true",
                    help="render ONE story-only MP3 (deliverable 1): keeps only "
                         "gamescript-bound lines (non-empty speaker), auto-picks "
                         "the highest standard MP3 bitrate that fits --target-mb, "
                         "and prints the chosen kbps + predicted size before "
                         "encoding (ignores --bitrate)")
    ap.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE_KBPS,
                    help="MP3 CBR bitrate in kbps (drives both encode and the "
                         "byte-budget packing math). Default %(default)s")
    ap.add_argument("--target-mb", type=float, default=285.0,
                    help="Target MB per reel file (default 285; output stays safely "
                         "under the 290 MB buffer)")
    ap.add_argument("--uniform-mono", action="store_true",
                    help="clips are all mono/48k/s16 (FW fast-path): skip normalize, "
                         "direct concat (fast + low disk at bulk scale)")
    a = ap.parse_args(argv)

    tiers = {t.strip() for t in a.tiers.split(",") if t.strip()}
    try:
        manifest_rows = read_csv_rows(a.manifest, required=REQUIRED_COLS)
    except FileNotFoundError:
        # Running render before full-reel (issue #311): the file doesn't exist
        # at all. Sibling of the CsvFormatError arm below -- a MISSING manifest
        # and a MALFORMED one are different diagnostics, both rc 1.
        print(f"render: ERROR - {a.manifest} does not exist -- expected a "
              f"full-reel manifest. Run `deciwaves fw full-reel` first.")
        return 1
    except CsvFormatError as e:
        print(f"render: ERROR - {e}. Expected a full-reel manifest -- run "
              f"`deciwaves fw full-reel`.")
        return 1
    spine = build_spine(manifest_rows, bound_tiers=tiers)
    print(f"FW reel ({a.stem}): {len(spine)} lines across "
          f"{len({s.episode for s in spine})} episodes")

    if spine:
        os.makedirs(a.out_dir, exist_ok=True)
        def dur_of(s):
            wav = os.path.join(a.audio_root, s.wav)
            with wave.open(wav) as w:
                dur = w.getnframes() / float(w.getframerate())
            return wav, dur
        durations, ep_secs, n_failed = accumulate_episode_seconds(
            spine, dur_of, gap_key=lambda s: s.quest, err_key=lambda s: s.wav,
            errors_path=a.errors, catch=(OSError, wave.Error))
        if n_failed:
            print(f"measure: {n_failed} clip(s) failed (see {a.errors})")
    else:
        durations, ep_secs, n_failed = {}, {}, 0

    columns = ReelColumns(
        header=["timestamp", "quest", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.quest, s.speaker, s.subtitle, s.line_id])

    if a.single_file:
        return finish_single_file(
            spine, not manifest_rows, a.errors,
            msg_empty_input=(
                f"render: ERROR - {a.manifest} has no rows -- upstream "
                f"produced no lines to render. Run `deciwaves fw "
                f"full-reel`; no file written to {a.out_dir}."
            ),
            msg_empty_selection=(
                f"render: nothing to render: none of the {len(manifest_rows)} "
                f"rows in {a.manifest} match --tiers {a.tiers} -- no file "
                f"written to {a.out_dir}."
            ),
            msg_nothing_decoded=(
                f"render: ERROR - none of the {len(spine)} manifest clips could "
                f"be measured (see {a.errors}). Are the "
                f"manifest's wav paths present under --audio-root "
                f"({a.audio_root})? Run `deciwaves fw extract` first if this "
                f"workspace has no decoded audio yet."
            ),
            msg_zero_story=(
                f"render: ERROR - none of the {len(spine)} spine lines is story "
                f"(all are gamescript-unbound subtitle-only lines). Deliverable 1 "
                f"needs gamescript-bound lines -- run `deciwaves fw match` with a "
                f"BYO gamescript first; no file written to {a.out_dir}."
            ),
            durations=durations,
            out_dir=a.out_dir, cache_dir=a.cache, stem=a.stem, columns=columns,
            gap_key=lambda s: s.quest,
            story_predicate=is_story,
            _assemble=assemble_single_file,
            concat_fn=_concat_uniform if a.uniform_mono else None,
            silence_fn=mono_silence_wav if a.uniform_mono else None,
            unit_label="lines")
    return finish_render(
        spine, not manifest_rows, a.errors,
        msg_empty_input=(
            f"render: ERROR - {a.manifest} has no rows -- upstream "
            f"produced no lines to render. Re-run `deciwaves fw "
            f"full-reel`; no reels written to {a.out_dir}."
        ),
        msg_empty_selection=(
            f"render: nothing to render: none of the {len(manifest_rows)} "
            f"rows in {a.manifest} match --tiers {a.tiers} -- no reels "
            f"written to {a.out_dir}."
        ),
        msg_nothing_decoded=(
            f"render: ERROR - none of the {len(spine)} manifest clips could "
            f"be measured (see {a.errors}). Are the "
            f"manifest's wav paths present under --audio-root "
            f"({a.audio_root})? Run `deciwaves fw extract` first if this "
            f"workspace has no decoded audio yet."
        ),
        msg_zero_files=(
            f"render: ERROR - 0 reel files written to {a.out_dir} from "
            f"{len(spine)} spine lines -- see {a.errors}."
        ),
        durations=durations, ep_secs=ep_secs,
        out_dir=a.out_dir, cache_dir=a.cache, stem=a.stem, columns=columns,
        budget=budget_seconds(target_mb=a.target_mb, kbps=a.bitrate),
        gap_key=lambda s: s.quest,
        _assemble=assemble_reels,
        concat_fn=_concat_uniform if a.uniform_mono else None,
        silence_fn=mono_silence_wav if a.uniform_mono else None,
        concat_kwargs={"kbps": a.bitrate})


if __name__ == "__main__":
    raise SystemExit(main())
