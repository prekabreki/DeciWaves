"""Unit tests for the FW subtitle fast-path binder.

The pure logic — markup cleaning, within-group ASR<->subtitle assignment, and
manifest row building — is install-independent and tested here. The graph/scan
glue is exercised by the integration test in test_fw_object_reader.py (skips
without the install).
"""
import pytest

from deciwaves.games.fw import subtitle_bind
from deciwaves.games.fw.subtitle_bind import (
    clean_subtitle, assign_subtitles, build_subtitle_rows, types_json_error,
)
from deciwaves.games.fw.bind import MANIFEST_COLS


def test_clean_subtitle_strips_markup_and_newlines():
    s = "<time0.17>You have wandered.\nBut you are lost no more."
    assert clean_subtitle(s) == "You have wandered. But you are lost no more."


def test_clean_subtitle_collapses_internal_markup_and_whitespace():
    assert clean_subtitle("We say, <time1.99>reach\n\nfor   the stars!") == \
        "We say, reach for the stars!"


def test_assign_subtitles_recovers_scrambled_pairing():
    # subtitles in a DIFFERENT order than the clips' transcripts — the core
    # spike finding: positional k-th pairing is wrong, assignment recovers it.
    subtitles = ["the cat sat on the mat",
                 "hello there my old friend",
                 "goodbye for now everyone"]
    transcripts = ["hello there my old friend",       # clip 0
                   "goodbye for now everyone",         # clip 1
                   "the cat sat on the mat"]           # clip 2
    pairs = assign_subtitles(subtitles, transcripts)
    # pairs are (subtitle_idx, clip_idx, score), sorted by clip_idx
    assert [(s, c) for s, c, _ in pairs] == [(1, 0), (2, 1), (0, 2)]
    assert all(score >= 90 for _, _, score in pairs)


def test_assign_subtitles_unequal_counts_assigns_min():
    # mismatch group: 3 clips but only 2 subtitles -> 2 assignments, no crash
    subtitles = ["alpha bravo charlie delta", "echo foxtrot golf hotel"]
    transcripts = ["zulu yankee xray whiskey",         # clip 0 (a bark, no sub)
                   "echo foxtrot golf hotel",           # clip 1
                   "alpha bravo charlie delta"]         # clip 2
    pairs = assign_subtitles(subtitles, transcripts)
    assert sorted((s, c) for s, c, _ in pairs) == [(0, 2), (1, 1)]


def test_build_rows_uses_exact_subtitle_as_label_and_orders_by_group_then_clip():
    groups = [
        {"group_id": 42,
         "clips": [
             {"line_id": "g42_0000", "lssr_index": 0, "wav": "audio/g42_0000.wav",
              "transcript": "hello there my old friend"},
             {"line_id": "g42_0001", "lssr_index": 1, "wav": "audio/g42_0001.wav",
              "transcript": "the cat sat on the mat"},
         ],
         "subtitles": ["The cat sat on the mat.", "Hello there, my old friend!"]},
    ]
    rows = build_subtitle_rows(groups, accept=60.0)
    assert [r["line_id"] for r in rows] == ["g42_0000", "g42_0001"]
    # exact in-game subtitle is the label, not the ASR transcript
    assert rows[0]["subtitle"] == "Hello there, my old friend!"
    assert rows[1]["subtitle"] == "The cat sat on the mat."
    assert rows[0]["transcript"] == "hello there my old friend"
    # schema + ordering counter
    assert list(rows[0].keys()) == MANIFEST_COLS
    assert [r["gamescript_index"] for r in rows] == [0, 1]
    assert all(r["tier"] == "S" for r in rows)
    assert rows[0]["speaker"] == ""  # subtitle path gives no speaker


def test_build_rows_drops_low_score_multi_line_but_keeps_certain_single():
    groups = [
        # multi-line group: one clip is unintelligible ASR (music) -> its
        # assignment is low-confidence and must be dropped, not mislabeled.
        {"group_id": 7,
         "clips": [
             {"line_id": "g7_0000", "lssr_index": 0, "wav": "a/0.wav",
              "transcript": "the quick brown fox jumps over"},
             {"line_id": "g7_0001", "lssr_index": 1, "wav": "a/1.wav",
              "transcript": "lalala instrumental music nonsense zzz"},
         ],
         "subtitles": ["The quick brown fox jumps over.",
                       "An entirely unrelated spoken line here."]},
        # single-line group: pairing is certain regardless of ASR quality.
        {"group_id": 9,
         "clips": [
             {"line_id": "g9_0000", "lssr_index": 0, "wav": "a/9.wav",
              "transcript": "[music]"},
         ],
         "subtitles": ["This subtitle is certain."]},
    ]
    rows = build_subtitle_rows(groups, accept=60.0)
    ids = {r["line_id"] for r in rows}
    assert "g7_0000" in ids          # good match kept
    assert "g7_0001" not in ids      # low-confidence multi-line pairing dropped
    assert "g9_0000" in ids          # single-line certain pairing kept
    g9 = next(r for r in rows if r["line_id"] == "g9_0000")
    assert g9["subtitle"] == "This subtitle is certain."


# ---------------------------------------------------------------------------
# --types-json: actionable failure when the BYO Decima RTTI type map is
# missing, instead of a bare open() traceback (issue #7). Was previously a
# gitignored `vendor/odradek/...` dev-machine path that no stock user has.
# ---------------------------------------------------------------------------

def test_types_json_error_none_when_file_present(tmp_path):
    p = tmp_path / "types.json"
    p.write_text("{}", encoding="utf-8")
    assert types_json_error(str(p)) is None


def test_types_json_error_message_when_missing(tmp_path):
    p = tmp_path / "types.json"
    msg = types_json_error(str(p))
    assert msg is not None
    assert "--types-json" in msg
    assert "Forbidden West" in msg
    assert "docs/BYO.md" in msg
    # public-flip hygiene: no dev-machine path residue anywhere user-visible
    assert "vendor/odradek" not in msg


def test_main_missing_default_types_json_fails_actionably(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = subtitle_bind.main(["--package-dir", str(tmp_path / "pkg")])
    assert rc == 1

    captured = capsys.readouterr()
    assert "--types-json" in captured.out
    assert "types.json" in captured.out
    assert "docs/BYO.md" in captured.out
    assert "vendor/odradek" not in captured.out
    assert captured.err == ""  # no traceback


def test_main_missing_explicit_types_json_fails_actionably(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "my-types.json"
    rc = subtitle_bind.main(["--package-dir", str(tmp_path / "pkg"),
                             "--types-json", str(explicit)])
    assert rc == 1

    captured = capsys.readouterr()
    assert "--types-json" in captured.out
    assert repr(str(explicit)) in captured.out
    assert "docs/BYO.md" in captured.out
    assert captured.err == ""  # no traceback


def test_main_present_types_json_proceeds_past_the_check(tmp_path, monkeypatch):
    """With types.json present (the workspace-root default), main() must move
    on to the next real step instead of stopping at our new check -- proven by
    letting it reach (and fail on) the next, unrelated missing input, rather
    than repeating the types.json-missing message."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "types.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        subtitle_bind.main(["--package-dir", str(tmp_path / "no-such-package")])
