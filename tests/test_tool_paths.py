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
