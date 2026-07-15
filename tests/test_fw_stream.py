"""FwStreamStore raw-payload branch: bare-machine synthetic-bytes tests.

The raw branch (non-DSAR file) does a plain seek+read with no length check --
a read that crosses EOF used to return fewer bytes than requested with no
error, propagating a short/garbage clip. Mirrors the dsar_archive hardening
(see tests/test_dsar_archive.py).
"""
import re

import pytest

from deciwaves.engine.pack.fw_stream import FwStreamStore


def _write_raw(tmp_path, name, payload):
    (tmp_path / name).write_bytes(payload)
    return FwStreamStore(str(tmp_path), [name])


def test_raw_read_in_range_unchanged(tmp_path):
    store = _write_raw(tmp_path, "raw.bin", b"HELLO-DECIMA-" * 10)
    assert store.read(0, 0, 13) == b"HELLO-DECIMA-"
    assert store.read(0, 13, 13) == b"HELLO-DECIMA-"


def test_raw_read_past_eof_raises_not_silent_truncation(tmp_path):
    payload = b"A" * 100
    store = _write_raw(tmp_path, "raw.bin", payload)
    path = str(tmp_path / "raw.bin")
    with pytest.raises(ValueError, match=re.escape(path)):
        store.read(0, 90, 50)   # only 10 bytes remain -> short read
    with pytest.raises(ValueError, match=re.escape(path)):
        store.read(0, 200, 10)  # entirely past EOF -> zero bytes
