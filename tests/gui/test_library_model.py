"""Qt-free library model (#70, spec §6). NO importorskip -- must pass on the base
``.[test]`` install. Covers loading (story-order artifact vs catalog fallback, per-game
column mapping, DS artifacts in ``out/`` root vs HZD/FW under ``out/<game>/``), dupe +
has-subtitle marking, every filter, sort by each column, the FW WAV-header duration reader,
the HZD b_samples length join, all selection commands, and the selection.json round-trip.
"""
import csv
import os
import wave

from conftest import catalog_row

from deciwaves.gui.library_model import (
    LineRow,
    availability_by_id,
    check_all,
    check_none,
    distinct_speakers,
    empty_state_message,
    has_known_lengths,
    load_lines,
    load_selection,
    preview_available,
    save_selection,
    selection_path,
    sort_rows,
    uncheck_barks,
    uncheck_shorter_than,
    visible_rows,
    wav_duration_seconds,
)

# Verified on-disk artifact schemas (see games/{ds,hzd,fw}).
DS_CAT = ["line_id", "core_path", "line_index", "category", "scene", "speaker_code",
          "speaker_name", "subtitle_en", "wem_path_en", "language"]
DS_PLAY = ["episode", "is_side", "pos", "section", "scene", "line_index", "track_index",
           "category", "speaker", "subtitle", "stream_path", "line_id"]
HZD_MANIFEST = ["clip_row", "offset", "line_id", "speaker_name", "subtitle_en", "scene",
                "tier", "score", "transcript"]
HZD_CLIPIDX = ["clip_row", "offset", "a_bytes", "b_samples"]
FW_CLIPIDX = ["line_id", "group_id", "lssr_index", "file_index", "offset", "clip_bytes", "wav"]
FW_FULL = ["line_id", "wav", "speaker", "subtitle", "gamescript_index", "quest", "tier",
           "score", "transcript"]


def _write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_wav(path, seconds, framerate=8000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nframes = int(seconds * framerate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nframes)


def _play_row(**kw):
    base = dict(episode="1", is_side="0", pos="1.0", section="0", scene="sc", line_index="0",
                track_index="0", category="cutscene", speaker="Sam", subtitle="hi",
                stream_path="a/b.core.stream", line_id="p1")
    base.update(kw)
    return base


# --- loading ---------------------------------------------------------------

def test_load_missing_returns_empty(tmp_path):
    ws = str(tmp_path)
    assert load_lines(ws, "ds") == []
    assert load_lines(ws, "hzd") == []
    assert load_lines(ws, "fw") == []


def test_ds_artifacts_in_out_root_and_playlist_preferred(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "catalog.csv"), DS_CAT,
               [catalog_row(line_id="c1", subtitle_en="from catalog", speaker_name="Deadman")])
    rows = load_lines(ws, "ds")
    assert [r.line_id for r in rows] == ["c1"]
    assert rows[0].subtitle == "from catalog" and rows[0].speaker == "Deadman"

    # playlist (story order) wins once it exists
    _write_csv(os.path.join(ws, "out", "playlist.csv"), DS_PLAY,
               [_play_row(line_id="p1", speaker="Sam", subtitle="from playlist")])
    rows = load_lines(ws, "ds")
    assert [r.line_id for r in rows] == ["p1"]
    assert rows[0].speaker == "Sam" and rows[0].subtitle == "from playlist"
    assert rows[0].order_index == 0


def test_hzd_under_game_dir_manifest_preferred_and_length_joined(tmp_path):
    ws = str(tmp_path)
    # catalog only -> used, no length (DS 10-col schema, wem_path_en empty)
    _write_csv(os.path.join(ws, "out", "hzd", "catalog.csv"), DS_CAT,
               [catalog_row(line_id="h1", subtitle_en="cat line", wem_path_en="",
                            speaker_name="Aloy", category="ambient")])
    rows = load_lines(ws, "hzd")
    assert [r.line_id for r in rows] == ["h1"]
    assert rows[0].length_s is None and rows[0].category == "ambient"

    # asr-manifest wins once present; length joined via clip-index b_samples / 48000
    _write_csv(os.path.join(ws, "out", "hzd", "clip-index.csv"), HZD_CLIPIDX,
               [{"clip_row": "7", "offset": "0", "a_bytes": "100", "b_samples": "48000"}])
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_MANIFEST,
               [{"clip_row": "7", "offset": "0", "line_id": "m1", "speaker_name": "Aloy",
                 "subtitle_en": "bound line", "scene": "mq010", "tier": "S", "score": "100",
                 "transcript": "x"}])
    rows = load_lines(ws, "hzd")
    assert [r.line_id for r in rows] == ["m1"]
    assert rows[0].speaker == "Aloy" and rows[0].tier == "S"
    assert rows[0].length_s == 1.0  # 48000 samples / 48000 Hz


def test_hzd_length_none_when_b_samples_zero_or_no_clip_index(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "hzd", "asr-manifest.csv"), HZD_MANIFEST,
               [{"clip_row": "7", "offset": "0", "line_id": "m1", "speaker_name": "A",
                 "subtitle_en": "s", "scene": "mq", "tier": "S", "score": "1", "transcript": ""}])
    # no clip-index at all
    assert load_lines(ws, "hzd")[0].length_s is None
    # b_samples 0 (fact-count parse failed for that clip) -> None, not 0.0
    _write_csv(os.path.join(ws, "out", "hzd", "clip-index.csv"), HZD_CLIPIDX,
               [{"clip_row": "7", "offset": "0", "a_bytes": "100", "b_samples": "0"}])
    assert load_lines(ws, "hzd")[0].length_s is None


def test_fw_under_game_dir_full_reel_preferred_and_wav_length(tmp_path):
    ws = str(tmp_path)
    wav_rel = "audio/f1.wav"
    _write_wav(os.path.join(ws, "out", "fw", wav_rel), seconds=2.0)
    _write_csv(os.path.join(ws, "out", "fw", "clip-index.csv"), FW_CLIPIDX,
               [{"line_id": "f1", "group_id": "0", "lssr_index": "0", "file_index": "0",
                 "offset": "0", "clip_bytes": "10", "wav": wav_rel}])
    rows = load_lines(ws, "fw")
    assert [r.line_id for r in rows] == ["f1"]
    assert rows[0].has_subtitle is False  # clip-index carries no subtitle
    assert abs(rows[0].length_s - 2.0) < 0.05

    # full-reel manifest wins; carries speaker/subtitle/tier
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": wav_rel, "speaker": "Varl", "subtitle": "Hello Aloy",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    rows = load_lines(ws, "fw")
    assert rows[0].speaker == "Varl" and rows[0].subtitle == "Hello Aloy"
    assert rows[0].has_subtitle is True and rows[0].tier == "S"
    assert abs(rows[0].length_s - 2.0) < 0.05


def test_fw_subtitle_manifest_used_when_no_full_reel(tmp_path):
    """A FW user with types.json but NO BYO gamescript runs extract->asr->subtitle-bind and
    gets ONLY subtitle-manifest-full.csv (full-reel is gamescript-gated). The Library must use
    it -- it carries subtitles + speaker (same MANIFEST_COLS schema) -- not the subtitle-less
    clip-index.csv (spec §6.1: subtitle-manifest-full -> full-reel)."""
    ws = str(tmp_path)
    wav_rel = "audio/f1.wav"
    _write_wav(os.path.join(ws, "out", "fw", wav_rel), seconds=2.0)
    # clip-index also present (subtitle-manifest-full must win over it)
    _write_csv(os.path.join(ws, "out", "fw", "clip-index.csv"), FW_CLIPIDX,
               [{"line_id": "f1", "group_id": "0", "lssr_index": "0", "file_index": "0",
                 "offset": "0", "clip_bytes": "10", "wav": wav_rel}])
    _write_csv(os.path.join(ws, "out", "fw", "subtitle-manifest-full.csv"), FW_FULL,
               [{"line_id": "f1", "wav": wav_rel, "speaker": "Varl", "subtitle": "Hello Aloy",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    rows = load_lines(ws, "fw")
    assert [r.line_id for r in rows] == ["f1"]
    assert rows[0].speaker == "Varl" and rows[0].subtitle == "Hello Aloy"
    assert rows[0].has_subtitle is True and rows[0].tier == "S"
    assert abs(rows[0].length_s - 2.0) < 0.05


def test_fw_full_reel_wins_over_subtitle_manifest(tmp_path):
    """When both exist, the gamescript-anchored full-reel manifest is the richer story-order
    source, so it wins over subtitle-manifest-full (spec §6.1 precedence)."""
    ws = str(tmp_path)
    wav_rel = "audio/f1.wav"
    _write_wav(os.path.join(ws, "out", "fw", wav_rel), seconds=2.0)
    _write_csv(os.path.join(ws, "out", "fw", "subtitle-manifest-full.csv"), FW_FULL,
               [{"line_id": "f1", "wav": wav_rel, "speaker": "FromSubtitle", "subtitle": "sub",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    _write_csv(os.path.join(ws, "out", "fw", "full-reel-manifest.csv"), FW_FULL,
               [{"line_id": "f1", "wav": wav_rel, "speaker": "FromFullReel", "subtitle": "full",
                 "gamescript_index": "1", "quest": "MQ", "tier": "S", "score": "9",
                 "transcript": "x"}])
    rows = load_lines(ws, "fw")
    assert rows[0].speaker == "FromFullReel" and rows[0].subtitle == "full"


def test_fw_length_none_when_wav_absent(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "fw", "clip-index.csv"), FW_CLIPIDX,
               [{"line_id": "f9", "group_id": "0", "lssr_index": "0", "file_index": "0",
                 "offset": "0", "clip_bytes": "10", "wav": "audio/f9.wav"}])
    assert load_lines(ws, "fw")[0].length_s is None


def test_load_tolerates_utf8_bom(tmp_path):
    """A UTF-8 BOM must not corrupt the first header: without utf-8-sig the first column
    becomes '\\ufeffline_id', so every line_id parses as '' (issues #59/#84 BOM theme)."""
    ws = str(tmp_path)
    path = os.path.join(ws, "out", "catalog.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM-prefixed
        w = csv.DictWriter(f, fieldnames=DS_CAT)
        w.writeheader()
        w.writerow(catalog_row(line_id="c1", subtitle_en="hi", speaker_name="Sam"))
    rows = load_lines(ws, "ds")
    assert [r.line_id for r in rows] == ["c1"]
    assert rows[0].subtitle == "hi" and rows[0].speaker == "Sam"


# --- WAV-header duration reader --------------------------------------------

def test_wav_duration_seconds_reads_header(tmp_path):
    p = os.path.join(str(tmp_path), "x.wav")
    _write_wav(p, seconds=1.5, framerate=16000)
    assert abs(wav_duration_seconds(p) - 1.5) < 0.01


def test_wav_duration_seconds_none_on_missing_or_garbage(tmp_path):
    assert wav_duration_seconds(os.path.join(str(tmp_path), "missing.wav")) is None
    bad = os.path.join(str(tmp_path), "bad.wav")
    with open(bad, "wb") as f:
        f.write(b"not a wav file at all, no RIFF here")
    assert wav_duration_seconds(bad) is None


# --- dupe / subtitle marking -----------------------------------------------

def test_dupe_marking_within_scene(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "catalog.csv"), DS_CAT, [
        catalog_row(line_id="a", scene="s1", subtitle_en="same"),
        catalog_row(line_id="b", scene="s1", subtitle_en="same"),   # dupe of a
        catalog_row(line_id="c", scene="s2", subtitle_en="same"),   # other scene -> not a dupe
        catalog_row(line_id="d", scene="s1", subtitle_en="other"),
        catalog_row(line_id="e", scene="s1", subtitle_en=""),       # empty never dupes
        catalog_row(line_id="f", scene="s1", subtitle_en=""),
    ])
    rows = {r.line_id: r for r in load_lines(ws, "ds")}
    assert rows["a"].is_dupe is False and rows["b"].is_dupe is True
    assert rows["c"].is_dupe is False and rows["d"].is_dupe is False
    assert rows["e"].is_dupe is False and rows["f"].is_dupe is False


def test_has_subtitle_detection(tmp_path):
    ws = str(tmp_path)
    _write_csv(os.path.join(ws, "out", "catalog.csv"), DS_CAT, [
        catalog_row(line_id="a", subtitle_en="Hello"),
        catalog_row(line_id="b", subtitle_en=""),
        catalog_row(line_id="c", subtitle_en="(none)"),
        catalog_row(line_id="d", subtitle_en="   "),
    ])
    rows = {r.line_id: r for r in load_lines(ws, "ds")}
    assert rows["a"].has_subtitle is True
    assert rows["b"].has_subtitle is False
    assert rows["c"].has_subtitle is False
    assert rows["d"].has_subtitle is False


# --- filters ---------------------------------------------------------------

def _rows():
    return [
        LineRow(line_id="a", speaker="Sam", subtitle="Hello world", has_subtitle=True,
                scene="s", order_index=0),
        LineRow(line_id="b", speaker="Amelie", subtitle="Goodbye", has_subtitle=True,
                scene="s", order_index=1),
        LineRow(line_id="c", speaker="Sam", subtitle="", has_subtitle=False,
                scene="s", order_index=2),
        LineRow(line_id="d", speaker="Sam", subtitle="Hello world", has_subtitle=True,
                is_dupe=True, scene="s", order_index=3),
    ]


def test_visible_rows_search_over_subtitle():
    out = visible_rows(_rows(), search="hello", speaker="all", hide_dupes=False,
                       hide_no_subtitle=False)
    assert {r.line_id for r in out} == {"a", "d"}


def test_visible_rows_search_over_line_id():
    rows = [LineRow(line_id="ZZZ_special", subtitle="nothing here", has_subtitle=True,
                    order_index=0)]
    out = visible_rows(rows, search="zzz_spec", speaker="all", hide_dupes=False,
                       hide_no_subtitle=False)
    assert len(out) == 1


def test_visible_rows_speaker_filter():
    out = visible_rows(_rows(), search="", speaker="Sam", hide_dupes=False,
                       hide_no_subtitle=False)
    assert {r.line_id for r in out} == {"a", "c", "d"}


def test_visible_rows_hide_dupes():
    out = visible_rows(_rows(), search="", speaker="all", hide_dupes=True,
                       hide_no_subtitle=False)
    assert "d" not in {r.line_id for r in out}


def test_visible_rows_hide_no_subtitle():
    out = visible_rows(_rows(), search="", speaker="all", hide_dupes=False,
                       hide_no_subtitle=True)
    assert "c" not in {r.line_id for r in out}


def test_distinct_speakers_sorted_no_blanks():
    rows = _rows() + [LineRow(line_id="z", speaker=None, order_index=9),
                      LineRow(line_id="y", speaker="", order_index=10)]
    assert distinct_speakers(rows) == ["Amelie", "Sam"]


# --- sort ------------------------------------------------------------------

def test_sort_by_columns_and_default_order():
    rows = [
        LineRow(line_id="a", speaker="Zed", length_s=3.0, order_index=0),
        LineRow(line_id="b", speaker="Al", length_s=1.0, order_index=1),
        LineRow(line_id="c", speaker="Mo", length_s=None, order_index=2),
    ]
    assert [r.line_id for r in sort_rows(rows, None, False)] == ["a", "b", "c"]
    assert [r.line_id for r in sort_rows(rows, "length_s", False)] == ["b", "a", "c"]  # None last
    assert [r.line_id for r in sort_rows(rows, "speaker", False)] == ["b", "c", "a"]   # Al,Mo,Zed
    assert sort_rows(rows, "length_s", True)[0].line_id == "a"  # 3.0 first descending


def test_has_known_lengths():
    assert has_known_lengths([LineRow(line_id="a", length_s=None)]) is False
    assert has_known_lengths([LineRow(line_id="a", length_s=None),
                              LineRow(line_id="b", length_s=1.0)]) is True


# --- selection persistence -------------------------------------------------

def test_selection_path_under_game_gui_dir_for_all_games(tmp_path):
    ws = str(tmp_path)
    # DS pipeline artifacts sit in out/ root, but the GUI selection namespace is out/ds/gui/
    assert selection_path(ws, "ds") == os.path.join(ws, "out", "ds", "gui", "selection.json")
    assert selection_path(ws, "hzd") == os.path.join(ws, "out", "hzd", "gui", "selection.json")


def test_selection_roundtrip_atomic(tmp_path):
    ws = str(tmp_path)
    assert load_selection(ws, "ds") == set()  # missing -> everything checked
    save_selection(ws, "ds", {"x", "y"})
    assert load_selection(ws, "ds") == {"x", "y"}
    gui_dir = os.path.join(ws, "out", "ds", "gui")
    assert os.listdir(gui_dir) == ["selection.json"]  # atomic write left no temp file


def test_selection_corrupt_returns_empty(tmp_path):
    ws = str(tmp_path)
    p = selection_path(ws, "ds")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert load_selection(ws, "ds") == set()


# --- selection commands ----------------------------------------------------

def test_check_all_and_none():
    rows = _rows()
    assert check_all(rows) == set()
    assert check_none(rows) == {"a", "b", "c", "d"}


def test_uncheck_shorter_than_ignores_unknown_length_and_unions():
    rows = [
        LineRow(line_id="a", length_s=1.0, order_index=0),
        LineRow(line_id="b", length_s=5.0, order_index=1),
        LineRow(line_id="c", length_s=None, order_index=2),
    ]
    assert uncheck_shorter_than(rows, set(), 3.0) == {"a"}
    assert uncheck_shorter_than(rows, {"z"}, 3.0) == {"a", "z"}


def test_uncheck_barks_hzd():
    rows = [
        LineRow(line_id="amb", category="ambient", subtitle="noise", has_subtitle=True),
        LineRow(line_id="empty", subtitle="", has_subtitle=False),
        LineRow(line_id="keep", subtitle="A real line", has_subtitle=True),
    ]
    assert uncheck_barks(rows, set(), "hzd") == {"amb", "empty"}


def test_uncheck_barks_fw_wordfloor():
    rows = [
        LineRow(line_id="nosub", subtitle="", has_subtitle=False),
        LineRow(line_id="oneword", subtitle="Hey", has_subtitle=True),
        LineRow(line_id="keep", subtitle="Two words", has_subtitle=True),
    ]
    assert uncheck_barks(rows, set(), "fw") == {"nosub", "oneword"}


def test_uncheck_barks_ds_empty_subtitle():
    rows = [
        LineRow(line_id="empty", subtitle="", has_subtitle=False),
        LineRow(line_id="keep", subtitle="Hello", has_subtitle=True),
    ]
    assert uncheck_barks(rows, set(), "ds") == {"empty"}


# --- preview availability --------------------------------------------------

def test_preview_available_per_game():
    """Cheap availability (spec §6.2/§6.5): no per-row filesystem syscall on the paint path.
    DS always; HZD only once bind is done; FW iff the row has a WAV path (extract wrote the
    WAVs -- we do NOT stat each of 40k rows on scroll)."""
    assert preview_available(LineRow(line_id="a"), "ds", bind_done=False) is True
    assert preview_available(LineRow(line_id="a"), "hzd", bind_done=False) is False
    assert preview_available(LineRow(line_id="a"), "hzd", bind_done=True) is True

    # FW: non-empty audio_path -> available (no os.path.exists); empty/None -> not
    assert preview_available(LineRow(line_id="f1", audio_path="out/fw/audio/f1.wav"),
                             "fw", bind_done=True) is True
    assert preview_available(LineRow(line_id="f2", audio_path=None), "fw", bind_done=True) is False
    assert preview_available(LineRow(line_id="f3", audio_path=""), "fw", bind_done=True) is False


def test_availability_by_id_lookup_is_cheap_and_per_row():
    rows = [LineRow(line_id="a", audio_path="x.wav"), LineRow(line_id="b", audio_path=None)]
    # FW: per-row on audio_path
    assert availability_by_id(rows, "fw", bind_done=True) == {"a": True, "b": False}
    # HZD: single bind bool for every row, regardless of audio_path
    assert availability_by_id(rows, "hzd", bind_done=False) == {"a": False, "b": False}
    assert availability_by_id(rows, "hzd", bind_done=True) == {"a": True, "b": True}
    # DS: always available
    assert availability_by_id(rows, "ds", bind_done=False) == {"a": True, "b": True}


# --- empty / no-results overlay (#121) -------------------------------------

def test_empty_state_message_no_catalog():
    """No rows loaded at all -> guidance to run Scan (audit H6, #121)."""
    assert empty_state_message(0, 0) == "No catalog yet - run Scan on the Pipeline tab"


def test_empty_state_message_filters_hide_everything():
    """A non-empty catalog whose filters exclude every row -> a *different* message."""
    assert empty_state_message(5, 0) == "No lines match - clear filters"


def test_empty_state_message_none_when_rows_visible():
    """Rows to show -> no overlay (the grid speaks for itself)."""
    assert empty_state_message(5, 3) is None
    assert empty_state_message(5, 5) is None


def test_empty_state_message_uses_ascii_hyphens():
    """User-facing strings use ASCII hyphens, never em-dashes (repo convention)."""
    for msg in (empty_state_message(0, 0), empty_state_message(3, 0)):
        assert msg is not None
        assert "—" not in msg and "–" not in msg
        assert " - " in msg
