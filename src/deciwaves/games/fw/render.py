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
from dataclasses import dataclass

import subprocess

from deciwaves.engine.catalog_io import read_csv_rows, CsvFormatError
from deciwaves.engine.render import (
    SR, DEFAULT_BITRATE_KBPS, accumulate_episode_seconds, assemble_reels,
    budget_seconds, format_ts, ReelColumns,
)

# Default --manifest: the full-reel stage (story_full.py)'s own default --out.
# Keep these in lockstep -- see test_render_default_manifest_matches_full_reel_stage_output.
DEFAULT_MANIFEST = "out/fw/full-reel-manifest.csv"
# Default --tiers: every tier the full-reel manifest actually ships, INCLUDING
# "S" (subtitle-only, no gamescript match) -- that's most of the full reel's
# lines; dropping it silently would defeat the point of the full-reel deliverable.
DEFAULT_TIERS = "1,2,S"
BOUND_TIERS = {t.strip() for t in DEFAULT_TIERS.split(",") if t.strip()}
MONO_FMT = (1, SR, 2)        # FW fast-path clips are all mono / 48 kHz / s16


def mono_silence_wav(seconds, cache_dir):
    """Mono 48 kHz s16 silence, matching the FW clip format (for the fast concat)."""
    import wave
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"silence_mono_{int(seconds * 1000)}ms.wav")
    if os.path.isfile(path):
        return path
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"\x00\x00" * int(seconds * SR))
    return path


def _is_mono(wav):
    import wave
    try:
        with wave.open(wav) as w:
            return (w.getnchannels(), w.getframerate(), w.getsampwidth()) == MONO_FMT
    except Exception:
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


@dataclass
class RenderItem:
    gamescript_index: int
    episode: int            # dense rank of the quest (the packing unit)
    quest: str
    speaker: str
    subtitle: str
    line_id: str
    wav: str                # path relative to the audio root


def build_spine(manifest_rows, bound_tiers=BOUND_TIERS) -> list[RenderItem]:
    """Ordered playlist of bound lines, sorted by gamescript index.

    Each distinct quest becomes a dense episode index (the packing unit), assigned
    in gamescript order. Lines whose tier is not in ``bound_tiers`` are dropped.
    """
    rows = [r for r in manifest_rows if r["tier"].strip() in bound_tiers]
    rows.sort(key=lambda r: int(r["gamescript_index"]))
    ep_of: dict[str, int] = {}
    spine = []
    for r in rows:
        ep_of.setdefault(r["quest"], len(ep_of))
        spine.append(RenderItem(
            gamescript_index=int(r["gamescript_index"]),
            episode=ep_of[r["quest"]], quest=r["quest"],
            speaker=r["speaker"], subtitle=r["subtitle"],
            line_id=r["line_id"], wav=r["wav"]))
    return spine


# Columns build_spine reads. A manifest missing any of them -- a garbled
# header, or the wrong CSV entirely -- would otherwise crash build_spine with a
# raw `KeyError`; validate up front for a clean, actionable error (issue #84,
# mirroring the #7/#23 message convention).
REQUIRED_COLS = ("line_id", "gamescript_index", "quest", "tier",
                 "speaker", "subtitle", "wav")


class ManifestError(Exception):
    """A manifest that can't be rendered (missing/garbled required columns)."""


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
    except CsvFormatError as e:
        print(f"render: ERROR - {e}. Expected a full-reel manifest -- run "
              f"`deciwaves fw full-reel`.")
        return 1
    spine = build_spine(manifest_rows, bound_tiers=tiers)
    print(f"FW reel ({a.stem}): {len(spine)} lines across "
          f"{len({s.episode for s in spine})} episodes")
    if not spine:
        # Checked HERE, before measure/assemble side effects (cache writes,
        # pack read). Drop a stale render-errors.log from a PRIOR run: measure
        # (its only writer, which rewrites it each run) never runs on either
        # branch below, so a leftover log would otherwise be misread as this
        # run's failures.
        try:
            os.remove(a.errors)
        except OSError:
            pass
        if not manifest_rows:
            # Empty INPUT: a header-only manifest means an upstream stage
            # produced nothing -- a broken/empty pipeline, not a selection.
            # Fail LOUD (issue #85) so `fw run`/the GUI stage strip can't show
            # render green with zero audio end-to-end -- the empty-input
            # sub-case of the partial-rip-looks-complete failure #64/#63/#81
            # exist to kill.
            print(f"render: ERROR - {a.manifest} has no rows -- upstream "
                  f"produced no lines to render. Re-run `deciwaves fw "
                  f"full-reel`; no reels written to {a.out_dir}.")
            return 1
        # Empty SELECTION: rows present, none matched the tier filter. A
        # legitimate NO-OP, not a failure -- DS's empty-playlist precedent
        # (review of #64: `--tiers D` is endorsed by the flag's help yet never
        # matches the standard full-reel manifest, DLC ships via
        # games/fw/dlc.py's own manifest; failing would make a deliberate no-op
        # indistinguishable from a broken pipeline).
        print(f"render: nothing to render: none of the {len(manifest_rows)} "
              f"rows in {a.manifest} match --tiers {a.tiers} -- no reels "
              f"written to {a.out_dir}.")
        return 0

    os.makedirs(a.out_dir, exist_ok=True)

    # measure each existing clip once; accumulate per-episode duration (incl. gaps)
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
    # Empty-render guard (issue #64), same contract as engine/render.py's DS
    # guard: a spine where NOTHING could be measured (typically: the manifest's
    # wav paths don't exist on disk) is a failure, not a zero-clip "success".
    # (spine is known non-empty here -- the no-op case returned 0 above.)
    if not durations:
        print(f"render: ERROR - none of the {len(spine)} manifest clips could "
              f"be measured (see {a.errors}). Are the "
              f"manifest's wav paths present under --audio-root "
              f"({a.audio_root})? Run `deciwaves fw extract` first if this "
              f"workspace has no decoded audio yet.")
        return 1

    columns = ReelColumns(
        header=["timestamp", "quest", "speaker", "subtitle", "line_id"],
        row_of=lambda s, t: [format_ts(t), s.quest, s.speaker, s.subtitle, s.line_id])
    n_files = assemble_reels(
        spine, ep_secs, durations, out_dir=a.out_dir, cache_dir=a.cache, stem=a.stem,
        columns=columns, budget=budget_seconds(target_mb=a.target_mb, kbps=a.bitrate), gap_key=lambda s: s.quest,
        concat_fn=_concat_uniform if a.uniform_mono else None,
        silence_fn=mono_silence_wav if a.uniform_mono else None,
        concat_kwargs={"kbps": a.bitrate})
    if n_files == 0:
        # Defensive backstop (issue #64): with the `not durations` guard above,
        # a non-empty durations always packs >=1 reel, so this is unreachable
        # today -- kept as a cheap honest-exit-code guard in case assemble_reels'
        # contract ever changes, since `run`/the GUI trust this stage's rc.
        print(f"render: ERROR - 0 reel files written to {a.out_dir} from "
              f"{len(spine)} spine lines -- see {a.errors}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
