"""Regression for issue #52: the dev-tool ``tools/hzd_extract_ids.py`` must namespace a
no-name line's fallback id by its core path (mirroring ``catalog.py``), so ``line_ids.csv``
still joins 1:1 with ``catalog.csv`` and unnamed lines in different cores don't collide.

The tool called ``parse_sentence_ids(core_bytes, ...)`` WITHOUT ``core_path`` after #47
namespaced fallback ids, so every unnamed line got a constant ``<hash8('')>#sentence#N``
prefix -- reintroducing the exact cross-core collision #47 fixed, and breaking the
docstring's "joins 1:1 with catalog.csv" promise.
"""
import csv

from tools import hzd_extract_ids
from deciwaves.games.hzd.sentence_fw import _fallback_line_id, parse_sentences_fw
from test_fixtures_sentence_fw import _unnamed_line_core_bytes

CORE_PATH = "localized/sentences/mq/naming/sentences"


class _FakeReader:
    def __init__(self, cores):
        self.cores = cores

    def read_core(self, path):
        return self.cores[path]


class _FakeProfile:
    def __init__(self, reader):
        self.pack_reader = reader


def test_fallback_line_id_is_namespaced_by_core_path(tmp_path, monkeypatch):
    reader = _FakeReader({CORE_PATH: _unnamed_line_core_bytes()})
    # build_profile / harvest_sentence_cores are imported inside main(); patch them at
    # their source module so the local `from ... import` picks up the stand-ins.
    monkeypatch.setattr("deciwaves.games.hzd.profile.build_profile",
                        lambda package: _FakeProfile(reader))
    monkeypatch.setattr("deciwaves.games.hzd.inventory.harvest_sentence_cores",
                        lambda fw, sample_cap=None: [CORE_PATH])
    monkeypatch.setattr(hzd_extract_ids, "select_sentence_cores", lambda harvested: list(harvested))

    out = tmp_path / "line_ids.csv"
    rc = hzd_extract_ids.main([
        "--package", "FAKE",
        "--out", str(out),
        "--errors", str(tmp_path / "line_ids-errors.log"),
    ])
    assert rc == 0

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    emitted = rows[0]["line_id"]

    # The 1:1 join promise: the tool must emit the SAME line_id the catalog stage
    # produces when it parses that same core with the same core_path.
    expected = parse_sentences_fw(_unnamed_line_core_bytes(), core_path=CORE_PATH)[0].line_id
    assert emitted == expected
    assert emitted == _fallback_line_id(CORE_PATH, 0)
    # Regression guard: NOT the constant hash8('') prefix the bug produced.
    assert emitted != _fallback_line_id("", 0)
