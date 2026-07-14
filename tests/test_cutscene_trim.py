from deciwaves.games.ds import cutscene_trim as ct


def _rows():
    return [
        {"scene": "sq_cs00_s00100", "status": "resolved", "track_index": "0",
         "voice_track_stream": "a.core.stream"},
        {"scene": "sq_cs71_s00270", "status": "resolved", "track_index": "0",
         "voice_track_stream": "grunt.core.stream"},
        {"scene": "sq_cs00_s00200", "status": "no_voice_track", "track_index": "0",
         "voice_track_stream": ""},
    ]


def test_run_builds_keepspans_and_drops_pure_grunt():
    decode = lambda sp: ("wav_" + sp, 60.0)
    def transcribe(wav):
        if "grunt" in wav:
            return [{"start": 1.0, "end": 1.2}]          # 0.2s speech -> dropped
        return [{"start": 2.0, "end": 5.0}]              # 3s speech -> kept
    results, errors = ct.run(_rows(), decode, transcribe, min_speech=1.0)
    assert errors == []
    by = {r["stream_path"]: r for r in results}
    assert by["a.core.stream"]["dropped"] == 0
    assert by["a.core.stream"]["keep_spans"] == "1.65:5.35"
    assert by["a.core.stream"]["line_id"] == "sq_cs00_s00100#track0"
    assert by["grunt.core.stream"]["dropped"] == 1
    assert by["grunt.core.stream"]["keep_spans"] == ""
    assert "grunt.core.stream" in by and len(results) == 2  # unresolved row skipped


def test_run_skips_already_done():
    decode = lambda sp: ("wav", 60.0)
    transcribe = lambda wav: [{"start": 2.0, "end": 5.0}]
    results, _ = ct.run(_rows(), decode, transcribe, done={"a.core.stream"})
    assert [r["stream_path"] for r in results] == ["grunt.core.stream"]


def test_run_fail_soft_on_decode_error():
    def decode(sp):
        if "grunt" in sp:
            raise RuntimeError("boom")
        return ("wav", 60.0)
    transcribe = lambda wav: [{"start": 2.0, "end": 5.0}]
    results, errors = ct.run(_rows(), decode, transcribe)
    assert [r["stream_path"] for r in results] == ["a.core.stream"]
    assert errors and errors[0][0] == "grunt.core.stream" and "boom" in errors[0][1]
