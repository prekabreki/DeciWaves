"""WhisperX transcription wrapper (ASR content-binding / validation pass). Game-agnostic:
used by HZD's ASR content-binding (`games/hzd/asr_bind.py`), FW's transcript pass
(`games/fw/asr_run.py`) and DLC labeling (`games/fw/dlc.py`), and DS's cutscene
speech-region trim (`games/ds/cutscene_trim.py`). Heavy GPU deps — install with
`pip install deciwaves[asr]` (plus a CUDA-matched torch build)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Transcript:
    text: str
    speech_ratio: float


def _prefer_copy_over_symlink():
    """Windows non-admin: huggingface_hub's symlink probe races under its threaded
    download and calls os.symlink in a window where it wrongly believes symlinks
    work, raising WinError 1314 (not a PermissionError, so HF's copy-fallback misses
    it). Symlinks are genuinely unsupported here, so pin the probe to False -> HF
    copies instead. No-op where symlinks actually work. Lazy import keeps the base
    module importable without huggingface_hub (see test_asr)."""
    try:
        import huggingface_hub.file_download as _fd
        if not _fd.are_symlinks_supported():
            _fd.are_symlinks_supported = lambda *a, **k: False
    except Exception:
        pass


def load_model(name="large-v3", device="cuda", compute_type="float16", initial_prompt=None):
    """Load a WhisperX model. ``initial_prompt`` primes decoding with domain proper
    nouns (FW character roster) to cut name mistranscriptions; passed through
    faster-whisper's ASR options. None leaves whisperx defaults untouched."""
    _prefer_copy_over_symlink()                       # before whisperx pulls models
    import whisperx                                   # lazy: keep base import light
    asr_options = {"initial_prompt": initial_prompt} if initial_prompt else None
    return whisperx.load_model(name, device, compute_type=compute_type, asr_options=asr_options)


def _load_audio(path):
    import whisperx                                   # lazy: keep base import light
    return whisperx.load_audio(path)


def _load_audio_seconds(path):
    import wave
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())


def transcribe(wav_path, model, batch_size=16, language=None):
    # Pinning ``language`` (e.g. "en") skips whisperx's per-clip language detection —
    # faster and more robust on short clips that can misdetect. None = auto-detect.
    kw = {"language": language} if language else {}
    result = model.transcribe(_load_audio(wav_path), batch_size=batch_size, **kw)
    segs = result.get("segments", [])
    text = " ".join(s["text"].strip() for s in segs).strip()
    speech = sum(s["end"] - s["start"] for s in segs)
    total = _load_audio_seconds(wav_path) or 1.0
    return Transcript(text, min(1.0, speech / total))


def transcribe_segments(wav_path, model, batch_size=16, language="en"):
    """Return the raw WhisperX segment dicts ({"start","end","text",...}) for a
    clip. Unlike ``transcribe`` (which keeps only aggregate speech_ratio), this
    preserves per-segment timing — needed to build keep-spans for cutscene trim
    (the cutscene speech-region trim). ``language`` defaults to "en" (cutscene VO); None = auto-detect."""
    kw = {"language": language} if language else {}
    result = model.transcribe(_load_audio(wav_path), batch_size=batch_size, **kw)
    return result.get("segments", [])
