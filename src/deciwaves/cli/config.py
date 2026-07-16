"""Persisted config: where setup put the tools and where the games live."""
import json
import os
import tempfile
from pathlib import Path
from typing import NamedTuple, Optional

KEYS = ("tools_dir", "ds_install", "hzd_package", "fw_package", "oodle_dll", "fw_gamescript")

# --- decode tool metadata -------------------------------------------------
# Single source of truth for the three decode tools `deciwaves setup` fetches.
# Previously triplicated -- main.py's _apply_config_env (exe name + env var,
# for PATH/env wiring), doctor.py's check_tool(...) call sites (display name +
# exe name + env var), and setup.py's own _TOOLS (label + url + exe) each
# spelled the same facts out independently, with the exe name spelled two
# different ways between them ("vgmstream-cli.exe" in main.py/setup.py vs.
# bare "vgmstream-cli" in doctor.py) (issue #32). `key`/`display` keep their
# two previously-distinct spellings (setup's short summary-row label vs.
# doctor's own display name) so consolidating this doesn't change either
# module's printed text -- only the facts themselves (exe filename, env var,
# URL) are now defined exactly once.

# Pinned 2026-07-14 via:
#   gh release view --repo vgmstream/vgmstream --json assets -q '.assets[].name' | grep -i win
#   gh release view --repo Thealexbarney/VGAudio --json assets -q '.assets[].name'
#   gh release view autobuild-2026-07-14-13-19 --repo BtbN/FFmpeg-Builds --json assets -q '.assets[].name' | grep win64-gpl.zip
#
# BtbN/FFmpeg-Builds has no versioned tags -- "latest" is a rolling alias that
# always points at whatever the newest autobuild-YYYY-MM-DD-HH-MM release is,
# so it is NOT a pin (issue #39). Pin to that dated autobuild tag's master
# build instead, same as vgmstream/VGAudio pin to a fixed release/tag.
VGMSTREAM_URL = "https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip"
VGAUDIO_URL = "https://github.com/Thealexbarney/VGAudio/releases/download/v2.2.1/VGAudioCli.zip"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-14-13-19/ffmpeg-N-125608-g150f7d15df-win64-gpl.zip"


class ToolSpec(NamedTuple):
    key: str                       # setup's short summary-row label
    display: str                   # doctor's human display name
    exe: str                       # canonical exe filename (with .exe) in tools_dir
    env_var: Optional[str]         # explicit override env var, or None (ffmpeg has none)
    url: str                       # pinned download URL (issue #39)


TOOLS = (
    ToolSpec("vgmstream", "vgmstream-cli", "vgmstream-cli.exe", "DECIWAVES_VGMSTREAM", VGMSTREAM_URL),
    ToolSpec("VGAudio",   "VGAudioCli",    "VGAudioCli.exe",    "DECIWAVES_VGAUDIO",   VGAUDIO_URL),
    ToolSpec("ffmpeg",    "ffmpeg",        "ffmpeg.exe",        None,                  FFMPEG_URL),
)

def path() -> Path:
    root = os.environ.get("DECIWAVES_CONFIG_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "DeciWaves")
    return Path(root) / "config.json"

def _warn_corrupted(cfg_path: Path, reason) -> None:
    print(
        f"warning: config file {cfg_path} is corrupted ({reason}); "
        "ignoring it and starting fresh -- run `deciwaves setup` to repair."
    )

def load() -> dict:
    cfg_path = path()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        _warn_corrupted(cfg_path, exc)
        return {}
    if not isinstance(cfg, dict):
        _warn_corrupted(cfg_path, f"expected a JSON object, got {type(cfg).__name__}")
        return {}
    return cfg

def save(cfg: dict) -> None:
    cfg_path = path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({k: cfg.get(k, "") for k in KEYS}, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        dir=cfg_path.parent, prefix=cfg_path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_name, cfg_path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise
