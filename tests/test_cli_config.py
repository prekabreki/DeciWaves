import json

import pytest

from deciwaves.cli import config


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
