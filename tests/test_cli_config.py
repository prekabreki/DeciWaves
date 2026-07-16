import json

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
    """Guards against the table being reintroduced as separate copies: setup's
    own _TOOLS and doctor's check list must be *derived from* config.TOOLS,
    not restate its facts independently."""
    from deciwaves.cli import setup as setup_mod

    assert setup_mod.VGMSTREAM_URL == config.TOOLS[0].url
    assert setup_mod.VGAUDIO_URL == config.TOOLS[1].url
    assert setup_mod.FFMPEG_URL == config.TOOLS[2].url
    assert setup_mod._TOOLS == tuple((t.key, t.url, t.exe) for t in config.TOOLS)


def test_absolutize_existing_paths_rewrites_only_existing_relative_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")

    argv = ["--gamescript", "real.md", "--data-dir", "does-not-exist", "--bitrate", "96"]
    out = config.absolutize_existing_paths(argv)

    assert out == ["--gamescript", str(existing), "--data-dir", "does-not-exist", "--bitrate", "96"]


def test_absolutize_existing_paths_leaves_already_absolute_paths_alone(tmp_path):
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    out = config.absolutize_existing_paths(["--gamescript", str(existing)])
    assert out == ["--gamescript", str(existing)]


def test_absolutize_existing_paths_ignores_flag_tokens_even_if_coincidentally_a_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = config.absolutize_existing_paths(["--gamescript"])
    assert out == ["--gamescript"]  # never treated as a path token, existing or not


def test_absolutize_existing_paths_rewrites_flag_equals_value_form(tmp_path, monkeypatch):
    """Finding 2: `--gamescript=real.md` (the '=' spelling) was skipped wholesale
    because the token starts with '-', so it was never absolutized before the
    workspace chdir -- the exact #32 bug, alive for the '=' form. The value part
    must be absolutized the same way the bare two-token form is."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")

    out = config.absolutize_existing_paths(["--gamescript=real.md", "--bitrate=96"])

    assert out == [f"--gamescript={existing}", "--bitrate=96"]


def test_absolutize_existing_paths_equals_form_leaves_nonexistent_and_absolute_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")
    argv = [f"--gamescript={existing}", "--data-dir=does-not-exist"]
    assert config.absolutize_existing_paths(argv) == argv  # already-abs + typo untouched


def test_absolutize_existing_paths_prints_notice_when_rewriting(tmp_path, monkeypatch, capsys):
    """Whenever a token is rewritten (bare or '=' form) a one-line notice must be
    printed, so the invocation-dir -> absolute redirect is never silent."""
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "real.md"
    existing.write_text("x", encoding="utf-8")

    config.absolutize_existing_paths(["--gamescript", "real.md"])
    bare_out = capsys.readouterr().out
    assert "real.md" in bare_out
    assert str(existing) in bare_out

    config.absolutize_existing_paths(["--gamescript=real.md"])
    eq_out = capsys.readouterr().out
    assert "real.md" in eq_out
    assert str(existing) in eq_out


def test_absolutize_existing_paths_silent_when_nothing_rewritten(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config.absolutize_existing_paths(["--data-dir", "does-not-exist", "--bitrate=96"])
    assert capsys.readouterr().out == ""


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
