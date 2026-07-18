"""Qt-free `deciwaves setup` argv construction + summary/warning parsing (#68, spec §3,
§4). No importorskip: setup is game-free CLI plumbing, covered on a base install.

The summary parser is driven against `cli.setup._print_summary`'s REAL output (not a
re-typed copy of its f-string layout), so a format change there fails this test instead
of silently drifting -- the same anti-drift discipline as `parsed_stage_args` in conftest."""
import os

from deciwaves.cli import setup as cli_setup
from deciwaves.gui.setup_model import (
    build_setup_argv,
    parse_setup_summary,
    parse_setup_warnings,
)

BASE = ["py", "-m", "deciwaves.cli.main"]


# --- build_setup_argv ------------------------------------------------------

def test_bare_setup_is_just_the_setup_token():
    assert build_setup_argv(BASE) == [*BASE, "setup"]


def test_force_and_skip_downloads_are_boolean_flags():
    assert build_setup_argv(BASE, force=True) == [*BASE, "setup", "--force"]
    assert build_setup_argv(BASE, skip_downloads=True) == [*BASE, "setup", "--skip-downloads"]


def test_path_flags_are_absolutized(tmp_path, monkeypatch):
    # spec §4: the GUI always passes absolute paths for every path-valued flag.
    monkeypatch.chdir(tmp_path)
    argv = build_setup_argv(BASE, ds_install="game")
    val = argv[argv.index("--ds-install") + 1]
    assert os.path.isabs(val)
    assert val == os.path.abspath("game")


def test_empty_string_path_passes_through_to_clear():
    # `--flag ""` CLEARS a saved value (setup merge semantics); it must reach the CLI
    # verbatim, NOT get absolutized into the cwd.
    argv = build_setup_argv(BASE, hzd_package="")
    assert argv[argv.index("--hzd-package") + 1] == ""


def test_none_path_is_omitted_so_setup_keeps_the_saved_value():
    argv = build_setup_argv(BASE, fw_package=None)
    assert "--fw-package" not in argv


def test_all_path_flags_present_when_given():
    argv = build_setup_argv(BASE, ds_install="a", hzd_package="b", fw_package="c",
                            fw_gamescript="d", tools_dir="e")
    for flag in ("--ds-install", "--hzd-package", "--fw-package",
                 "--fw-gamescript", "--tools-dir"):
        assert flag in argv


# --- parse_setup_summary (driven by the real _print_summary) ---------------

def _real_summary(capsys, tool_rows, *, ds_install="", oodle_dll="", hzd_package="",
                  fw_package="", fw_gamescript=""):
    cli_setup._print_summary(tool_rows, ds_install, oodle_dll, hzd_package,
                             fw_package, fw_gamescript)
    return capsys.readouterr().out


def test_parses_fetched_found_and_failed_tool_rows(capsys):
    out = _real_summary(
        capsys,
        [("vgmstream", "fetched", r"C:\t\vgmstream-cli.exe"),
         # this status is 41 chars -- longer than the summary's 32-wide column, the
         # exact case a fixed-width slice would mangle:
         ("VGAudio", "found (skipped -- use --force to refetch)", r"C:\t\VGAudioCli.exe"),
         ("ffmpeg", "FAILED: ffmpeg (timed out)", r"C:\t\ffmpeg.exe")],
        ds_install=r"C:\Games\DS", oodle_dll=r"C:\Games\DS\oo2core_7_win64.dll")
    rows = {r.label: r for r in parse_setup_summary(out)}

    assert rows["vgmstream"].ok and not rows["vgmstream"].failed
    assert rows["VGAudio"].ok and not rows["VGAudio"].failed
    assert rows["ffmpeg"].failed and not rows["ffmpeg"].ok


def test_parses_missing_and_not_set_rows(capsys):
    out = _real_summary(
        capsys,
        [("vgmstream", "MISSING", r"C:\t\vgmstream-cli.exe")],
        ds_install=r"C:\Games\DS")  # oodle empty -> "MISSING"; hzd/fw unset -> "--"
    rows = {r.label: r for r in parse_setup_summary(out)}

    assert rows["vgmstream"].failed          # --skip-downloads, exe absent
    assert rows["oodle_dll"].failed          # ds set but DLL not located
    assert rows["ds_install"].ok
    # unset games are neither ok nor failed -- neutral
    assert not rows["hzd_pkg"].ok and not rows["hzd_pkg"].failed
    assert not rows["fw_pkg"].ok and not rows["fw_pkg"].failed


def test_parse_ignores_non_summary_lines():
    text = "some banner\nDownloading vgmstream...\n\nWrote C:\\x\\config.json\n"
    assert parse_setup_summary(text) == []


# --- parse_setup_warnings --------------------------------------------------

def test_extracts_oodle_and_hzd_warnings_verbatim(capsys):
    # real WARNING wording, straight from run_setup's emitters
    print(f"WARNING: {cli_setup.OODLE_DLL_NAME} not found under 'C:\\DS'. "
          "Point --ds-install at the DS:DC game root -- the folder that directly "
          f"contains {cli_setup.OODLE_DLL_NAME}, alongside ds.exe.")
    hzd_warn = cli_setup._hzd_package_warning(r"C:\Games\HZD")
    if hzd_warn:
        print(hzd_warn)
    out = capsys.readouterr().out

    warnings = parse_setup_warnings(out)
    assert any("oo2core_7_win64.dll" in w for w in warnings)
    assert all(w.startswith("WARNING:") for w in warnings)


def test_no_warnings_when_none_emitted():
    assert parse_setup_warnings("DeciWaves setup summary:\n  ffmpeg  ok  x\n") == []
