"""Packaged data files (ID/timing manifests + name rosters — never game prose)."""
from importlib.resources import files
from pathlib import Path


def packaged(rel: str) -> Path:
    p = Path(str(files("deciwaves.data"))) / rel
    if not p.is_file():
        raise FileNotFoundError(f"packaged data file not found: {rel}")
    return p
