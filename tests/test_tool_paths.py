from deciwaves.engine import tool_paths
from deciwaves.engine.tool_paths import resolve


def test_resolve_prefers_env_var_over_path(monkeypatch):
    monkeypatch.setenv("DECIWAVES_FAKE_TOOL", r"C:\explicit\tool.exe")
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: r"C:\on\path\tool.exe")
    assert resolve("DECIWAVES_FAKE_TOOL", "tool") == r"C:\explicit\tool.exe"


def test_resolve_falls_back_to_path_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which",
                         lambda name: r"C:\on\path\tool.exe" if name == "tool" else None)
    assert resolve("DECIWAVES_FAKE_TOOL", "tool") == r"C:\on\path\tool.exe"


def test_resolve_falls_back_to_bare_exe_name_when_nothing_found(monkeypatch):
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: None)
    assert resolve("DECIWAVES_FAKE_TOOL", "tool") == "tool"


def test_resolve_treats_empty_env_var_as_absent(monkeypatch):
    """An empty-string env var (e.g. a config layer that sets but doesn't populate
    it) must fall through to PATH/bare-name, not be treated as a real override."""
    monkeypatch.setenv("DECIWAVES_FAKE_TOOL", "")
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: None)
    assert resolve("DECIWAVES_FAKE_TOOL", "tool") == "tool"


# --- locate(): the shared env var -> tools_dir -> PATH order, plus WHICH source
# matched -- issue #51 item 1: doctor.check_tool used to reimplement this whole
# order independently instead of sharing it with resolve().

def test_locate_prefers_env_var_over_tools_dir_and_path(tmp_path, monkeypatch):
    (tmp_path / "tool.exe").write_bytes(b"x")
    monkeypatch.setenv("DECIWAVES_FAKE_TOOL", r"C:\explicit\tool.exe")
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: r"C:\on\path\tool.exe")
    found = tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool", str(tmp_path))
    assert found == (r"C:\explicit\tool.exe", "env")


def test_locate_finds_tools_dir_copy_between_env_and_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: r"C:\on\path\tool.exe")
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"x")
    found = tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool", str(tmp_path))
    assert found == (str(exe), "tools_dir")


def test_locate_falls_back_to_path_when_tools_dir_empty_or_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which",
                         lambda name: r"C:\on\path\tool.exe" if name == "tool" else None)
    assert tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool", str(tmp_path)) == \
        (r"C:\on\path\tool.exe", "PATH")
    assert tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool", "") == \
        (r"C:\on\path\tool.exe", "PATH")


def test_locate_reports_not_found_with_bare_name_and_empty_source(monkeypatch):
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: None)
    assert tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool") == ("tool", "")


def test_locate_with_empty_tools_dir_matches_resolves_two_source_behavior(monkeypatch):
    """tools_dir="" (resolve()'s implicit default) must reproduce the original
    env var -> PATH -> bare-name order byte for byte -- no existing call site
    (engine/audio_clip.py, games/fw/extract.py, games/hzd/atrac9.py) passes a
    tools_dir, so none of them may change behavior from this refactor."""
    monkeypatch.delenv("DECIWAVES_FAKE_TOOL", raising=False)
    monkeypatch.setattr(tool_paths.shutil, "which", lambda name: None)
    assert resolve("DECIWAVES_FAKE_TOOL", "tool") == \
        tool_paths.locate("DECIWAVES_FAKE_TOOL", "tool").path
