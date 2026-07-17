import json
import os

import pytest

from deciwaves.cli import config


# --- config.TOOLS: single source of truth for tool metadata (issue #32) ----
# Previously triplicated across main.py/_apply_config_env, doctor.py's
# check_tool(...) call sites, and setup.py's own _TOOLS -- with the exe name
# spelled two ways ("vgmstream-cli.exe" vs. bare "vgmstream-cli") between
# them. These characterize the shape every consumer relies on.

def test_tools_table_has_one_entry_per_decode_tool():
    keys = [t.key for t in config.TOOLS]
    assert keys == ["vgmstream", "VGAudio", "ffmpeg"]


def test_tools_table_exe_names_are_all_dot_exe():
    # The whole point of consolidating: one spelling, always with the
    # extension, instead of main.py/setup.py's ".exe" vs. doctor.py's bare name.
    for t in config.TOOLS:
        assert t.exe.lower().endswith(".exe")


def test_tools_table_only_ffmpeg_lacks_an_env_var():
    env_vars = {t.key: t.env_var for t in config.TOOLS}
    assert env_vars["vgmstream"] == "DECIWAVES_VGMSTREAM"
    assert env_vars["VGAudio"] == "DECIWAVES_VGAUDIO"
    assert env_vars["ffmpeg"] is None


def test_tools_table_urls_are_pinned_releases():
    for t in config.TOOLS:
        assert t.url.startswith("https://github.com/")
        assert "/releases/download/" in t.url


def test_setup_and_main_and_doctor_all_consume_the_same_tools_table():
    """Guards against the table being reintroduced as a separate copy: setup
    used to re-map config.TOOLS into an anonymous (key, url, exe) 3-tuple
    (`_TOOLS`) purely to unpack it positionally in `_fetch_tools` -- issue #51
    item 3 replaced that with `_fetch_tools` iterating config.TOOLS (ToolSpec)
    directly, so there is no second copy of the table left to drift."""
    from deciwaves.cli import setup as setup_mod

    assert setup_mod.VGMSTREAM_URL == config.TOOLS[0].url
    assert setup_mod.VGAUDIO_URL == config.TOOLS[1].url
    assert setup_mod.FFMPEG_URL == config.TOOLS[2].url
    assert not hasattr(setup_mod, "_TOOLS"), (
        "setup.py should iterate config.TOOLS directly, not keep a redundant "
        "_TOOLS re-mapping")


def test_absolutize_existing_paths_rewrites_only_existing_relative_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"  # distinct from cwd, and doesn't contain real.md

    argv = ["--gamescript", "real.md", "--data-dir", "does-not-exist", "--bitrate", "96"]
    out = config.absolutize_existing_paths(argv, workspace=str(workspace))

    assert out == ["--gamescript", str(existing), "--data-dir", "does-not-exist", "--bitrate", "96"]


def test_absolutize_existing_paths_leaves_already_absolute_paths_alone(tmp_path):
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"
    out = config.absolutize_existing_paths(["--gamescript", str(existing)], workspace=str(workspace))
    assert out == ["--gamescript", str(existing)]


def test_absolutize_existing_paths_ignores_flag_tokens_even_if_coincidentally_a_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "ws"
    out = config.absolutize_existing_paths(["--gamescript"], workspace=str(workspace))
    assert out == ["--gamescript"]  # never treated as a path token, existing or not


def test_absolutize_existing_paths_rewrites_flag_equals_value_form(tmp_path, monkeypatch):
    """Finding 2: `--gamescript=real.md` (the '=' spelling) was skipped wholesale
    because the token starts with '-', so it was never absolutized before the
    workspace chdir -- the exact #32 bug, alive for the '=' form. The value part
    must be absolutized the same way the bare two-token form is."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"

    out = config.absolutize_existing_paths(["--gamescript=real.md", "--bitrate=96"], workspace=str(workspace))

    assert out == [f"--gamescript={existing}", "--bitrate=96"]


def test_absolutize_existing_paths_equals_form_leaves_nonexistent_and_absolute_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"
    argv = [f"--gamescript={existing}", "--data-dir=does-not-exist"]
    assert config.absolutize_existing_paths(argv, workspace=str(workspace)) == argv  # already-abs + typo untouched


def test_absolutize_existing_paths_skips_until_and_from_stage_names(tmp_path, monkeypatch):
    """--until/--from take STAGE NAMES, never paths (run.py, issue #62): a cwd
    file/dir that happens to share a stage's name (`extract`, `render`, ...)
    must not get absolutized into an argparse-choices rejection. Path-taking
    flags in the same argv keep being rewritten."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "extract").mkdir()          # dir named like an fw stage
    (tmp_path / "render").write_text("x", encoding="utf-8")  # file named like a stage
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"

    argv = ["--until", "extract", "--from", "render", "--gamescript", "real.md"]
    out = config.absolutize_existing_paths(argv, workspace=str(workspace))

    assert out == ["--until", "extract", "--from", "render", "--gamescript", str(existing)]


def test_absolutize_existing_paths_skips_until_equals_form_too(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "extract").mkdir()
    workspace = tmp_path / "ws"

    out = config.absolutize_existing_paths(["--until=extract", "--from=extract"],
                                           workspace=str(workspace))

    assert out == ["--until=extract", "--from=extract"]


def test_absolutize_existing_paths_prints_notice_when_rewriting(tmp_path, monkeypatch, capsys):
    """Whenever a token is rewritten (bare or '=' form) a one-line notice must be
    printed, so the invocation-dir -> absolute redirect is never silent."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"

    config.absolutize_existing_paths(["--gamescript", "real.md"], workspace=str(workspace))
    bare_out = capsys.readouterr().out
    assert "real.md" in bare_out
    assert str(existing) in bare_out

    config.absolutize_existing_paths(["--gamescript=real.md"], workspace=str(workspace))
    eq_out = capsys.readouterr().out
    assert "real.md" in eq_out
    assert str(existing) in eq_out


def test_absolutize_existing_paths_silent_when_nothing_rewritten(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "ws"
    config.absolutize_existing_paths(["--data-dir", "does-not-exist", "--bitrate=96"], workspace=str(workspace))
    assert capsys.readouterr().out == ""


# --- issue #44: workspace-aware rewriting ----------------------------------
# The rewrite must stop being pure existence-based-against-cwd: a previous
# in-place run can leave e.g. `out/...` sitting under the invocation cwd, and
# a later `--workspace` run passing the same relative token got silently
# pinned to that OLD tree instead of the workspace one -- cross-workspace data
# mixing with no error (confirmed aggregate-review failure shape). The tests
# above cover the "workspace doesn't have it" case (unambiguous, absolutize);
# these cover the new no-workspace/no-op and ambiguous-refusal branches.

def test_absolutize_existing_paths_no_workspace_means_no_rewrite(tmp_path, monkeypatch, capsys):
    """No --workspace given at all (workspace=None, the default) -- nothing
    changes meaning across a chdir that isn't happening, so nothing should be
    rewritten or announced, unlike the old pure existence-based behavior."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")

    argv = ["--gamescript", "real.md"]
    out = config.absolutize_existing_paths(argv)

    assert out == argv
    assert capsys.readouterr().out == ""


def test_absolutize_existing_paths_workspace_same_as_cwd_means_no_rewrite(tmp_path, monkeypatch, capsys):
    """An explicit --workspace that resolves to the same directory as cwd (e.g.
    the argparse default `.`) must also skip rewriting entirely -- nothing is
    about to move, so nothing needs pinning."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")

    argv = ["--gamescript", "real.md"]
    out = config.absolutize_existing_paths(argv, workspace=".")

    assert out == argv
    assert capsys.readouterr().out == ""


def test_absolutize_existing_paths_missing_under_cwd_left_untouched_even_if_in_workspace(tmp_path, monkeypatch):
    """A token that doesn't exist relative to cwd is left alone even when a
    same-named file DOES exist under --workspace -- output paths stay
    workspace-relative, and a typo still fails the stage's own loud check the
    same way it always did (unchanged)."""
    invoke_dir = tmp_path / "invoke"
    invoke_dir.mkdir()
    monkeypatch.chdir(invoke_dir)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "real.md").write_text("workspace copy", encoding="utf-8")

    argv = ["--gamescript", "real.md"]
    out = config.absolutize_existing_paths(argv, workspace=str(workspace))

    assert out == argv  # untouched -- does not exist under cwd


def test_absolutize_existing_paths_refuses_when_both_exist_and_differ(tmp_path, monkeypatch, capsys):
    """The confirmed failure shape: a relative token exists under BOTH the
    invocation cwd and --workspace, and they're different files -- silently
    picking one (the old behavior) risks pinning to a stale tree. Must refuse
    loudly instead: exit 2, no stage runs, and the message names the token
    plus both candidate absolute paths so the user can pick one explicitly."""
    invoke_dir = tmp_path / "invoke"
    invoke_dir.mkdir()
    monkeypatch.chdir(invoke_dir)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cwd_file = invoke_dir / "real.md"
    cwd_file.write_text("cwd version", encoding="utf-8")
    ws_file = workspace / "real.md"
    ws_file.write_text("workspace version", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        config.absolutize_existing_paths(["--gamescript", "real.md"], workspace=str(workspace))

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "real.md" in err
    assert str(cwd_file.resolve()) in err
    assert str(ws_file.resolve()) in err


def test_absolutize_existing_paths_refuses_for_equals_form_too(tmp_path, monkeypatch, capsys):
    invoke_dir = tmp_path / "invoke"
    invoke_dir.mkdir()
    monkeypatch.chdir(invoke_dir)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (invoke_dir / "real.md").write_text("cwd version", encoding="utf-8")
    (workspace / "real.md").write_text("workspace version", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        config.absolutize_existing_paths(["--gamescript=real.md"], workspace=str(workspace))

    assert exc.value.code == 2
    assert "real.md" in capsys.readouterr().err


def test_absolutize_existing_paths_both_resolve_to_same_file_is_unambiguous(tmp_path, monkeypatch, capsys):
    """The workspace == subdir edge case: the token exists under both cwd and
    --workspace, but the two candidates are the SAME underlying file (e.g. a
    hardlink) rather than two different ones -- there's nothing ambiguous
    about that, so it should absolutize like the single-existing-copy case,
    not refuse."""
    invoke_dir = tmp_path / "invoke"
    invoke_dir.mkdir()
    monkeypatch.chdir(invoke_dir)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cwd_file = invoke_dir / "real.md"
    cwd_file.write_text("shared", encoding="utf-8")
    ws_file = workspace / "real.md"
    os.link(cwd_file, ws_file)  # same underlying file, two directory entries

    out = config.absolutize_existing_paths(["--gamescript", "real.md"], workspace=str(workspace))

    assert out == ["--gamescript", str(cwd_file.resolve())]
    assert "real.md" in capsys.readouterr().out  # still announced like any other rewrite


def test_load_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    assert config.load() == {}


def test_load_returns_empty_dict_and_warns_on_corrupted_json(tmp_path, monkeypatch, capsys):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    result = config.load()

    assert result == {}
    out = capsys.readouterr().out.lower()
    assert "warn" in out or "corrupt" in out or "invalid" in out


def test_load_returns_empty_dict_and_warns_on_truncated_file(tmp_path, monkeypatch, capsys):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("", encoding="utf-8")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    result = config.load()

    assert result == {}
    assert capsys.readouterr().out.strip() != ""


def test_load_returns_empty_dict_and_warns_on_non_utf8_file(tmp_path, monkeypatch, capsys):
    """Byte-level corruption (torn write; a tool re-saving as UTF-16 on this
    Windows-only project) raises UnicodeDecodeError -- a ValueError the old
    `except (json.JSONDecodeError, OSError)` did NOT cover, so load() crashed
    instead of warning and starting fresh (issue #81, shared with
    engine/coverage.py's artifact loader)."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_bytes(b"\xff\xfe not utf-8 \xff")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    result = config.load()

    assert result == {}
    out = capsys.readouterr().out.lower()
    assert "warn" in out or "corrupt" in out or "invalid" in out


@pytest.mark.parametrize("payload", ["null", "[1, 2]", '"a string"', "42"])
def test_load_returns_empty_dict_and_warns_on_non_object_json(
        tmp_path, monkeypatch, capsys, payload):
    # Valid JSON of the wrong type is corruption too: every caller does
    # cfg.get(...), so a null/list/scalar payload would brick commands
    # with AttributeError just like malformed JSON does.
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(payload, encoding="utf-8")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    result = config.load()

    assert result == {}
    assert capsys.readouterr().out.strip() != ""


def test_load_returns_empty_dict_and_warns_on_os_error(tmp_path, monkeypatch, capsys):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    # Make config.json a directory so read_text() raises an OSError
    # (IsADirectoryError / PermissionError), not JSONDecodeError.
    (cfg_dir / "config.json").mkdir()
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    result = config.load()

    assert result == {}
    assert capsys.readouterr().out.strip() != ""


def test_setup_can_repair_a_corrupted_config(tmp_path, monkeypatch):
    # This is the scenario the bug report cares about most: `deciwaves setup`
    # is the repair path, so it must not itself blow up on a corrupted
    # config.json -- it should recover and overwrite with a fresh, valid one.
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{corrupted", encoding="utf-8")
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    # load() must not raise -- this is what `setup` (and every other command)
    # calls first.
    cfg = config.load()
    assert cfg == {}

    config.save({"tools_dir": str(tmp_path / "tools")})

    repaired = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    assert repaired["tools_dir"] == str(tmp_path / "tools")


def test_save_writes_atomically_via_temp_file_and_replace(tmp_path, monkeypatch):
    # save() must not leave a half-written config.json behind if interrupted --
    # it should write to a temp file and os.replace() it into place, so
    # config.json is either the old complete content or the new complete
    # content, never a partial write.
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    config.save({"tools_dir": "first"})
    cfg_path = cfg_dir / "config.json"
    assert json.loads(cfg_path.read_text())["tools_dir"] == "first"

    # No leftover temp files after a normal save.
    leftovers = [p for p in cfg_dir.iterdir() if p.name != "config.json"]
    assert leftovers == []

    config.save({"tools_dir": "second"})
    assert json.loads(cfg_path.read_text())["tools_dir"] == "second"
    leftovers = [p for p in cfg_dir.iterdir() if p.name != "config.json"]
    assert leftovers == []


def test_save_uses_os_replace_not_direct_write(tmp_path, monkeypatch):
    # Directly verifies the fix's mechanism: save() must call os.replace (or
    # equivalent atomic rename) rather than writing straight to config.json.
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(cfg_dir))

    calls = []
    import os as os_module
    real_replace = os_module.replace

    def _spy_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os_module, "replace", _spy_replace)
    config.save({"tools_dir": "x"})

    assert len(calls) == 1
    src, dst = calls[0]
    assert str(dst).endswith("config.json")
    assert src != dst
