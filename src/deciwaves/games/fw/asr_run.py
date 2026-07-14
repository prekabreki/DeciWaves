"""FW ASR pass (transcript stage): transcribe every extracted clip into a match-key
transcript cache.

Resumable (skips `line_id`s already cached) and fail-soft (per-clip errors are
logged, never abort the run; a failed clip is simply absent and retried next
run). Rows are appended and flushed incrementally so a crash keeps progress.
The WhisperX model is primed with the FW character-name roster (`initial_prompt`)
to cut name mistranscriptions — see `load_initial_prompt`.

The transcription itself is injected (`transcribe_fn`) so the orchestration is
testable without the GPU stack; `main()` wires the real WhisperX model.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from deciwaves import data

TRANSCRIPT_COLS = ["line_id", "transcript", "speech_ratio"]

# Packaged roster's primer: a fenced block tagged ```initial_prompt.
_PROMPT_RE = re.compile(r"```initial_prompt\s*\n(.*?)\n```", re.S)
# Legacy fallback: the first bare fenced block after an "initial_prompt" heading
# (pre-Task-4 roster convention; kept so hand-authored rosters in that shape still work).
_PROMPT_RE_LEGACY = re.compile(r"initial_prompt.*?\n```\n(.*?)\n```", re.S | re.I)


def load_initial_prompt(roster_md: str | Path | None) -> str | None:
    """Extract the WhisperX `initial_prompt` proper-noun block from a roster doc.

    ``None`` resolves to the packaged default roster (`data.packaged("fw/character_names.md")`).
    ``""`` disables priming entirely (returns ``None``) -- e.g. for games/rosters not yet built.
    An explicit non-empty path that lacks the fenced block still raises ``ValueError``.
    """
    if roster_md == "":
        return None
    if roster_md is None:
        roster_md = data.packaged("fw/character_names.md")
    text = Path(roster_md).read_text(encoding="utf-8")
    m = _PROMPT_RE.search(text) or _PROMPT_RE_LEGACY.search(text)
    if not m:
        raise ValueError(f"no initial_prompt code block in {roster_md}")
    return " ".join(m.group(1).split())


def load_clip_index(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select_clips(rows, file_index=None, limit=0):
    """Subset clip rows by stream `file_index` (e.g. "101" = DLC) and/or a count cap."""
    if file_index:
        rows = [r for r in rows if r.get("file_index") == file_index]
    return rows[:limit] if limit else rows


def read_done_ids(transcripts_csv: str | Path) -> set[str]:
    p = Path(transcripts_csv)
    if not p.exists():
        return set()
    with p.open(newline="", encoding="utf-8") as f:
        return {row["line_id"] for row in csv.DictReader(f)}


def run(clip_rows, transcripts_csv, audio_root, transcribe_fn, log=print):
    """Transcribe each pending clip and append `(line_id, transcript, speech_ratio)`.

    `transcribe_fn(wav_path)` returns an object with `.text` and `.speech_ratio`.
    `audio_root` is the directory the clip-index `wav` paths are relative to
    (i.e. `out/fw`). Returns `(n_ok, n_err)`.
    """
    transcripts_csv = Path(transcripts_csv)
    audio_root = Path(audio_root)
    done = read_done_ids(transcripts_csv)
    pending = [r for r in clip_rows if r["line_id"] not in done]
    transcripts_csv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not transcripts_csv.exists()

    n_ok = n_err = 0
    with transcripts_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRANSCRIPT_COLS)
        if new_file:
            w.writeheader()
        for r in pending:
            wav = audio_root / r["wav"]
            try:
                t = transcribe_fn(str(wav))
                w.writerow({"line_id": r["line_id"], "transcript": t.text,
                            "speech_ratio": round(t.speech_ratio, 4)})
                f.flush()
                n_ok += 1
            except Exception as e:  # fail-soft: log and keep going
                log(f"ERROR {r['line_id']}: {e}")
                n_err += 1
    return n_ok, n_err


def main(argv=None):
    import argparse

    from deciwaves.games.hzd import asr

    ap = argparse.ArgumentParser(description="FW ASR transcript pass")
    ap.add_argument("--clip-index", default="out/fw/clip-index.csv")
    ap.add_argument("--audio-root", default="out/fw",
                    help="dir the clip-index 'wav' paths are relative to")
    ap.add_argument("--out", default="out/fw/transcripts.csv")
    ap.add_argument("--roster", default=None,
                    help="WhisperX initial_prompt roster doc; default = packaged "
                         "fw/character_names.md; '' disables priming")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--language", default="en",
                    help="pin transcription language (FW clips are all en); '' to auto-detect")
    ap.add_argument("--file-index", default="",
                    help="transcribe only clips from this stream file_index (e.g. 101 = DLC)")
    ap.add_argument("--limit", type=int, default=0, help="cap clips (0 = all)")
    a = ap.parse_args(argv)

    rows = select_clips(load_clip_index(a.clip_index),
                        file_index=a.file_index or None, limit=a.limit)
    prompt = load_initial_prompt(a.roster)
    model = asr.load_model(a.model, initial_prompt=prompt)
    print(f"clips={len(rows)} model={a.model} prompt_chars={len(prompt) if prompt else 0}")

    lang = a.language or None
    n_ok, n_err = run(
        rows, a.out, a.audio_root,
        transcribe_fn=lambda w: asr.transcribe(w, model, batch_size=a.batch_size, language=lang),
    )
    print(f"transcribed ok={n_ok} err={n_err} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
