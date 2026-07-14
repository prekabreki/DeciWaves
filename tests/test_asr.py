"""Unit tests for the WhisperX wrapper (asr.py). Stubs the model so whisperx is NOT required."""
from games.hzd.asr import transcribe


class _StubModel:
    # mimics whisperx result dict shape; records kwargs for forwarding tests
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, batch_size=16, **kw):
        self.calls.append({"batch_size": batch_size, **kw})
        return {"segments": [{"text": " I'll find a way ", "start": 0.0, "end": 2.0}]}


def test_asr_bind_imports_without_whisperx():
    import importlib, games.hzd.asr_bind
    importlib.reload(games.hzd.asr_bind)  # whisperx is not installed in the venv


def test_transcribe_concats_and_reports_speech_ratio(monkeypatch, tmp_path):
    # stub audio load -> 3.0s clip; 2.0s of speech => ratio ~0.667
    import games.hzd.asr as asr
    monkeypatch.setattr(asr, "_load_audio_seconds", lambda p: 3.0)
    monkeypatch.setattr(asr, "_load_audio", lambda p: object())
    t = transcribe(str(tmp_path / "x.wav"), _StubModel())
    assert t.text.strip() == "I'll find a way"
    assert 0.6 < t.speech_ratio < 0.7


def _stub_whisperx(monkeypatch):
    import sys
    import types
    captured = {}
    fake = types.ModuleType("whisperx")

    def load_model(name, device, compute_type="float16", asr_options=None):
        captured.update(name=name, device=device, asr_options=asr_options)
        return "MODEL"

    fake.load_model = load_model
    monkeypatch.setitem(sys.modules, "whisperx", fake)
    return captured


def test_load_model_primes_initial_prompt_as_asr_option(monkeypatch):
    captured = _stub_whisperx(monkeypatch)
    import games.hzd.asr as asr
    m = asr.load_model("large-v3-turbo", initial_prompt="Aloy, GAIA, HEPHAESTUS")
    assert m == "MODEL"
    assert captured["name"] == "large-v3-turbo"
    assert captured["asr_options"]["initial_prompt"] == "Aloy, GAIA, HEPHAESTUS"


def test_load_model_without_prompt_sends_no_asr_options(monkeypatch):
    captured = _stub_whisperx(monkeypatch)
    import games.hzd.asr as asr
    asr.load_model()
    assert captured["asr_options"] is None


def test_transcribe_forwards_language(monkeypatch, tmp_path):
    import games.hzd.asr as asr
    monkeypatch.setattr(asr, "_load_audio_seconds", lambda p: 2.0)
    monkeypatch.setattr(asr, "_load_audio", lambda p: object())
    model = _StubModel()
    asr.transcribe(str(tmp_path / "x.wav"), model, language="en")
    assert model.calls[0]["language"] == "en"


def test_transcribe_omits_language_when_unset(monkeypatch, tmp_path):
    import games.hzd.asr as asr
    monkeypatch.setattr(asr, "_load_audio_seconds", lambda p: 2.0)
    monkeypatch.setattr(asr, "_load_audio", lambda p: object())
    model = _StubModel()
    asr.transcribe(str(tmp_path / "x.wav"), model)
    assert "language" not in model.calls[0]


def test_transcribe_segments_returns_raw_segments(monkeypatch, tmp_path):
    import games.hzd.asr as asr
    monkeypatch.setattr(asr, "_load_audio", lambda p: object())
    model = _StubModel()  # returns one segment {text, start 0.0, end 2.0}
    segs = asr.transcribe_segments(str(tmp_path / "x.wav"), model)
    assert [(s["start"], s["end"]) for s in segs] == [(0.0, 2.0)]
    assert model.calls[0]["language"] == "en"  # pinned by default


def test_transcribe_segments_empty(monkeypatch, tmp_path):
    import games.hzd.asr as asr
    monkeypatch.setattr(asr, "_load_audio", lambda p: object())

    class _Empty:
        def transcribe(self, audio, batch_size=16, **kw):
            return {"segments": []}

    assert asr.transcribe_segments(str(tmp_path / "x.wav"), _Empty()) == []
