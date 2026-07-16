"""Persisted config: where setup put the tools and where the games live."""
import json
import os
import tempfile
from pathlib import Path

KEYS = ("tools_dir", "ds_install", "hzd_package", "fw_package", "oodle_dll", "fw_gamescript")

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
