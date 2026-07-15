"""The FW labeled-manifest schema (games/fw/manifest.py) is a cross-stage contract:
six stage modules and the renderer all read/write CSVs with these columns, and
downstream consumers index them by name and position."""
from deciwaves.games.fw.manifest import MANIFEST_COLS


def test_manifest_cols_order_stable():
    assert MANIFEST_COLS[:5] == [
        "line_id", "wav", "speaker", "subtitle", "gamescript_index"]
