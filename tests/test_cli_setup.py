import io
import json
import urllib.request
import zipfile

import pytest

from deciwaves.cli import setup as s


def test_setup_writes_config_and_finds_oodle(tmp_path, monkeypatch):
    ds = tmp_path / "DS"; ds.mkdir(); (ds / "oo2core_7_win64.dll").write_bytes(b"x"); (ds / "data").mkdir()
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest: None)
    rc = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["oodle_dll"].endswith("oo2core_7_win64.dll")
    assert cfg["ds_install"] == str(ds)


def test_setup_warns_but_succeeds_without_any_game(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest: None)
    assert s.run_setup(["--tools-dir", str(tmp_path / "t")]) == 0
    assert "no game install configured" in capsys.readouterr().out.lower()


def test_setup_warns_when_oodle_missing_under_ds_install(tmp_path, monkeypatch, capsys):
    ds = tmp_path / "DS_no_oodle"; ds.mkdir()  # no oo2core_7_win64.dll inside
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest: None)
    rc = s.run_setup(["--ds-install", str(ds), "--tools-dir", str(tmp_path / "tools")])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "oo2core_7_win64.dll" in out
    assert "not found" in out
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["oodle_dll"] == ""
    assert cfg["ds_install"] == str(ds)


def test_setup_saves_hzd_and_fw_package_paths(tmp_path, monkeypatch, capsys):
    hzd = tmp_path / "hzd.package"
    fw = tmp_path / "fw.package"
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest: None)
    rc = s.run_setup([
        "--tools-dir", str(tmp_path / "tools"),
        "--hzd-package", str(hzd),
        "--fw-package", str(fw),
    ])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "no game install configured" not in out
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["hzd_package"] == str(hzd)
    assert cfg["fw_package"] == str(fw)
    assert cfg["ds_install"] == ""


def test_skip_downloads_never_calls_download(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools"; tools_dir.mkdir()
    (tools_dir / "vgmstream-cli.exe").write_bytes(b"x")  # only one of the three present

    def _boom(url, dest):
        raise AssertionError("must not fetch when --skip-downloads is passed")

    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", _boom)
    rc = s.run_setup(["--tools-dir", str(tools_dir), "--skip-downloads"])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["tools_dir"] == str(tools_dir)


def test_default_tools_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("DECIWAVES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(s, "_download_and_unpack", lambda url, dest: None)
    rc = s.run_setup([])
    assert rc == 0
    cfg = json.loads((tmp_path / "cfg" / "config.json").read_text())
    assert cfg["tools_dir"] == str(tmp_path / "AppData" / "Local" / "DeciWaves" / "tools")


def test_download_and_unpack_flattens_nested_zip(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vgmstream-win64/vgmstream-cli.exe", b"exe-bytes")
        zf.writestr("vgmstream-win64/libvgmstream.dll", b"dll-bytes")
        zf.writestr("vgmstream-win64/docs/README.txt", b"read me")
    zip_bytes = buf.getvalue()

    monkeypatch.setattr(urllib.request, "urlopen", lambda url: io.BytesIO(zip_bytes))

    dest = tmp_path / "tools"
    s._download_and_unpack("https://example.invalid/vgmstream-win64.zip", dest)

    assert (dest / "vgmstream-cli.exe").read_bytes() == b"exe-bytes"
    assert (dest / "libvgmstream.dll").read_bytes() == b"dll-bytes"
    assert (dest / "README.txt").read_bytes() == b"read me"
    # flattened -- no nested folder survives
    assert not (dest / "vgmstream-win64").exists()
    assert not (dest / "docs").exists()


def test_find_oodle_empty_when_no_ds_install():
    assert s._find_oodle("") == ""


@pytest.mark.parametrize("url", [s.VGMSTREAM_URL, s.VGAUDIO_URL, s.FFMPEG_URL])
def test_pinned_urls_are_github_release_downloads(url):
    assert url.startswith("https://github.com/")
    assert "/releases/download/" in url
    assert url.endswith(".zip")
