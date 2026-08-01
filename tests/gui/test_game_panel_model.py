"""Qt-free per-game panel model (#73, spec §7): per-game control visibility, the FW
types.json grading, the scan-warning copy, the render-scope defaults, and the standalone
DS re-order argv. Base .[test] install -- NO importorskip (this module never imports
PySide6, mirroring test_export_model / test_pipeline_model)."""
import os

from deciwaves.gui.game_panel_model import (
    FW_TIERS_DEFAULT,
    FW_TIERS_HINT,
    GAMESCRIPT_FORMAT_HINT,
    SAMPLE_CAP_DEFAULT,
    check_gamescript,
    controls_for,
    effective_types_path,
    render_scope_defaults,
    scan_warning,
    transcript_order_argv,
    types_status,
    validate_fw_tiers,
)

BASE = ["py", "-m", "deciwaves.cli.main"]


# --- controls_for (hide-not-grey visibility set per game) ------------------

def test_controls_for_ds_is_transcript_and_main_story():
    ds = controls_for("ds")
    assert ds == {"transcript", "main_story"}
    # DS has no GPU block, no sample cap, no BYO pickers, no spine/tiers.
    assert "gpu" not in ds and "sample_cap" not in ds
    assert "types_json" not in ds and "gamescript" not in ds


def test_controls_for_hzd_is_gpu_sample_cap_spine_only():
    hzd = controls_for("hzd")
    assert hzd == {"gpu", "sample_cap", "spine_only"}
    # HZD has no BYO pickers, no transcript, no main-story/tiers.
    assert "transcript" not in hzd and "types_json" not in hzd
    assert "gamescript" not in hzd and "main_story" not in hzd


def test_controls_for_fw_is_gpu_types_gamescript_tiers():
    fw = controls_for("fw")
    assert fw == {"gpu", "types_json", "gamescript", "tiers"}
    # FW has no sample cap, no transcript, no main-story/spine-only.
    assert "sample_cap" not in fw and "transcript" not in fw
    assert "main_story" not in fw and "spine_only" not in fw


def test_controls_for_unknown_game_is_empty():
    assert controls_for("nope") == set()


# --- effective_types_path / types_status (FW gate grading) -----------------

def test_effective_types_path_defaults_to_workspace_root(tmp_path):
    ws = str(tmp_path)
    assert effective_types_path(ws, {}) == os.path.join(ws, "types.json")


def test_effective_types_path_uses_config_override(tmp_path):
    ws = str(tmp_path)
    override = os.path.join(ws, "elsewhere", "rtti.json")
    assert effective_types_path(ws, {"fw_types": override}) == override
    # an empty configured value falls back to the workspace default (config's "clear" state).
    assert effective_types_path(ws, {"fw_types": ""}) == os.path.join(ws, "types.json")


def test_types_status_missing_then_ok_on_workspace_default(tmp_path):
    ws = str(tmp_path)
    status, path = types_status(ws, {})
    assert status == "missing"
    assert path == os.path.join(ws, "types.json")
    open(path, "w").close()
    status, path = types_status(ws, {})
    assert status == "ok"


def test_types_status_follows_config_override(tmp_path):
    ws = str(tmp_path)
    override = os.path.join(ws, "rtti.json")
    assert types_status(ws, {"fw_types": override})[0] == "missing"
    open(override, "w").close()
    assert types_status(ws, {"fw_types": override})[0] == "ok"


# --- scan_warning (spec §7 copy -- introduced here) ------------------------

def test_scan_warning_per_game():
    assert "CPU" in scan_warning("ds")
    assert "hours" in scan_warning("hzd") and "GPU" in scan_warning("hzd")
    assert "asr" in scan_warning("fw") and "hours" in scan_warning("fw")
    assert scan_warning("nope") == ""


# --- render_scope_defaults / SAMPLE_CAP_DEFAULT ----------------------------

def test_sample_cap_default_is_300():
    assert SAMPLE_CAP_DEFAULT == 300


def test_render_scope_defaults_per_game():
    # DS defaults main-story OFF: the GUI's out-of-box export renders exactly the checked
    # rows (#72's contract), and --main-story is an opt-in scope-narrowing on top.
    assert render_scope_defaults("ds") == {"main_story": False}
    assert render_scope_defaults("hzd") == {"spine_only": False}
    assert render_scope_defaults("fw") == {"tiers": FW_TIERS_DEFAULT}
    assert FW_TIERS_DEFAULT == "1,2,S"
    assert render_scope_defaults("nope") == {}


# --- validate_fw_tiers -----------------------------------------------------

def test_validate_fw_tiers_default_is_valid():
    is_valid, unknown = validate_fw_tiers("1,2,S")
    assert is_valid is True
    assert unknown == []


def test_validate_fw_tiers_all_known_tiers_is_valid():
    is_valid, unknown = validate_fw_tiers("1,2,S,W,D")
    assert is_valid is True
    assert unknown == []


def test_validate_fw_tiers_single_tier_is_valid():
    for tier in ("1", "2", "S", "W", "D"):
        is_valid, unknown = validate_fw_tiers(tier)
        assert is_valid is True, f"tier {tier!r} should be valid"
        assert unknown == []


def test_validate_fw_tiers_unknown_token_is_flagged():
    is_valid, unknown = validate_fw_tiers("1,2,Z")
    assert is_valid is False
    assert "Z" in unknown


def test_validate_fw_tiers_multiple_unknown():
    is_valid, unknown = validate_fw_tiers("X,Y,1")
    assert is_valid is False
    assert set(unknown) == {"X", "Y"}


def test_validate_fw_tiers_empty_string_is_valid():
    is_valid, unknown = validate_fw_tiers("")
    assert is_valid is True
    assert unknown == []


def test_validate_fw_tiers_whitespace_and_order_agnostic():
    is_valid, unknown = validate_fw_tiers(" W , 2 , 1 , S ")
    assert is_valid is True
    assert unknown == []


def test_validate_fw_tiers_subset_finds_no_false_positive():
    for combo in ("W,D", "1,W", "S,D", "1,2,S,W,D"):
        is_valid, unknown = validate_fw_tiers(combo)
        assert is_valid is True, f"combo {combo!r} should be valid"
        assert unknown == []


def test_fw_tiers_hint_is_defined():
    assert isinstance(FW_TIERS_HINT, str)
    assert len(FW_TIERS_HINT) > 0


# --- transcript_order_argv (standalone DS re-order) ------------------------

def test_transcript_order_argv_is_standalone_order_with_abs_transcript(tmp_path):
    ws = str(tmp_path)
    transcript = tmp_path / "story.md"
    transcript.write_text("...", encoding="utf-8")
    argv = transcript_order_argv(BASE, ws, str(transcript))
    # standalone `order` (never `run`), workspace before the game token (spec §4).
    assert "run" not in argv
    assert argv[argv.index("--workspace") + 1] == os.path.abspath(ws)
    assert argv.index("--workspace") < argv.index("ds") < argv.index("order")
    assert argv[argv.index("--transcript") + 1] == os.path.abspath(str(transcript))
    # threads the packaged cutscene tracks so standalone order matches the chain's order.
    assert "--cutscene-tracks" in argv


# --- check_gamescript (BYO gamescript parse-check at pick time) ------------

def test_check_gamescript_ok_reports_lines_speakers_sections(tmp_path):
    p = tmp_path / "script.md"
    p.write_text(
        "THE EMBASSY\n"
        "Aloy: We should go.\n"
        "Varl: Right behind you.\n"
        "[Aloy climbs the cliff]\n"
        "Aloy: Almost there.\n",
        encoding="utf-8",
    )
    status, message = check_gamescript(str(p))
    assert status == "ok"
    assert "3 lines" in message          # the bracketed stage direction is not a line
    assert "2 speakers" in message
    assert "1 sections" in message


def test_check_gamescript_flags_wrong_format_as_empty(tmp_path):
    """The whole point: the parser never raises, so a wrong-shaped file must be caught here.

    Without this grade, picking such a file is indistinguishable from supplying none at all -
    subtitle_match has no empty guard and just writes a header-only manifest.
    """
    p = tmp_path / "wrong.md"
    p.write_text("[00:12] Aloy - We should go.\n**Varl:** Right behind you.\n", encoding="utf-8")
    status, message = check_gamescript(str(p))
    assert status == "empty"
    assert "no gamescript at all" in message.lower()
    assert GAMESCRIPT_FORMAT_HINT in message     # tells the user what it SHOULD look like


def test_check_gamescript_unreadable_when_missing(tmp_path):
    status, message = check_gamescript(str(tmp_path / "nope.md"))
    assert status == "unreadable"
    assert "could not read" in message.lower()


def test_check_gamescript_grade_matches_the_real_parser(tmp_path):
    """Guard against the grade drifting from what `fw match` will actually see."""
    from deciwaves.games.fw.gamescript import parse_file
    p = tmp_path / "script.md"
    p.write_text("A QUEST\nAloy: One.\nSylens: Two.\n", encoding="utf-8")
    status, message = check_gamescript(str(p))
    assert status == "ok"
    assert f"{len(parse_file(str(p))):,} lines" in message


def test_gamescript_format_hint_names_the_speaker_shape():
    assert "Speaker: text" in GAMESCRIPT_FORMAT_HINT
    assert "BYO.md" in GAMESCRIPT_FORMAT_HINT
