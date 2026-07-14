"""Persisted config: where setup put the tools and where the games live."""
import json
import os
from pathlib import Path

KEYS = ("tools_dir", "ds_install", "hzd_package", "fw_package", "oodle_dll")

def path() -> Path:
    root = os.environ.get("DECIWAVES_CONFIG_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "DeciWaves")
    return Path(root) / "config.json"

def load() -> dict:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}

def save(cfg: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps({k: cfg.get(k, "") for k in KEYS}, indent=2), encoding="utf-8")
