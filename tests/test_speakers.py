# tests/test_speakers.py
"""TDD tests for SpeakerMap."""
from unittest.mock import MagicMock, patch
import json
import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _make_fake_idx(core_map: dict):
    """Build a fake PackIndex that serves pre-canned bytes for given virtual paths."""
    fake_idx = MagicMock()

    def _read_core(vp):
        if vp not in core_map:
            raise KeyError(vp)
        return core_map[vp]

    fake_idx.read_core.side_effect = _read_core
    return fake_idx


def _fake_ltr_bytes(name: str):
    """Return a sentinel bytes value that the patched reader will turn into a LocalizedTextResource."""
    return name.encode("ascii")  # content doesn't matter; reader is mocked


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestNameFor:
    """name_for() extracts the vr-stem from a full voice path and looks it up."""

    def test_full_path_resolved(self):
        from deciwaves.engine.speakers import SpeakerMap
        smap = SpeakerMap.__new__(SpeakerMap)
        smap._map = {"vr0010_sam": "Sam", "vr0040_frg": "Fragile"}
        assert smap.name_for("localized/voices/vr0010_sam") == "Sam"

    def test_stem_only_resolved(self):
        from deciwaves.engine.speakers import SpeakerMap
        smap = SpeakerMap.__new__(SpeakerMap)
        smap._map = {"vr0010_sam": "Sam"}
        assert smap.name_for("vr0010_sam") == "Sam"

    def test_unknown_returns_empty_string(self):
        from deciwaves.engine.speakers import SpeakerMap
        smap = SpeakerMap.__new__(SpeakerMap)
        smap._map = {}
        assert smap.name_for("localized/voices/vr9999_nobody") == ""

    def test_empty_string_returns_empty_string(self):
        from deciwaves.engine.speakers import SpeakerMap
        smap = SpeakerMap.__new__(SpeakerMap)
        smap._map = {"vr0010_sam": "Sam"}
        assert smap.name_for("") == ""

    def test_name_for_trailing_slash(self):
        """name_for strips a trailing slash before extracting the stem."""
        from deciwaves.engine.speakers import SpeakerMap
        smap = SpeakerMap.__new__(SpeakerMap)
        smap._map = {"vr0010_sam": "Sam"}
        # Both forms must resolve to the same name.
        without = smap.name_for("localized/voices/vr0010_sam")
        with_slash = smap.name_for("localized/voices/vr0010_sam/")
        assert with_slash == without == "Sam"


class TestBuildMap:
    """_build_map() reads simpletext cores and builds {stem: name}."""

    def _run_build(self, file_list_lines, fake_idx, fake_ltr_by_path):
        """Patch away the Decima reader and call _build_map."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap

        def fake_read_objects(stream, objs):
            from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
            data = stream.read()
            # Look up which path this data came from
            for vp, b in fake_ltr_by_path.items():
                if data == b:
                    obj = MagicMock(spec=LocalizedTextResource)
                    obj.language = [data.decode("ascii")]
                    objs["obj0"] = obj
                    return
            # No match — leave objs empty

        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read_objects):
            return SpeakerMap._build_map(fake_idx, file_list_lines)

    def test_simple_resolution(self):
        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        b = _fake_ltr_bytes("Sam")
        fake_idx = _make_fake_idx({vp: b})
        result = self._run_build([vp], fake_idx, {vp: b})
        assert result == {"vr0010_sam": "Sam"}

    def test_absent_core_skipped(self):
        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        fake_idx = _make_fake_idx({})  # all absent
        result = self._run_build([vp], fake_idx, {})
        assert result == {}

    def test_parse_error_skipped(self):
        """If read_objects_from_stream raises, the entry is skipped gracefully."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        fake_idx = _make_fake_idx({vp: b"garbage"})

        with patch.object(reader, "read_objects_from_stream", side_effect=ValueError("boom")):
            result = SpeakerMap._build_map(fake_idx, [vp])
        assert result == {}

    def test_no_ltr_in_core_skipped(self):
        """If the core parses fine but contains no LocalizedTextResource, entry is skipped."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        fake_idx = _make_fake_idx({vp: b"data"})

        def no_ltr(stream, objs):
            pass  # no objects placed

        with patch.object(reader, "read_objects_from_stream", side_effect=no_ltr):
            result = SpeakerMap._build_map(fake_idx, [vp])
        assert result == {}

    def test_empty_language_list_skipped(self):
        """Empty language list in LTR → skip, no crash."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
        from deciwaves.engine.speakers import SpeakerMap

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        fake_idx = _make_fake_idx({vp: b"data"})

        def empty_ltr(stream, objs):
            obj = MagicMock(spec=LocalizedTextResource)
            obj.language = []
            objs["obj0"] = obj

        with patch.object(reader, "read_objects_from_stream", side_effect=empty_ltr):
            result = SpeakerMap._build_map(fake_idx, [vp])
        assert result == {}

    def test_multiple_voices_resolved(self):
        paths = {
            "localized/sentences/voices/vr0010_sam/simpletext": _fake_ltr_bytes("Sam"),
            "localized/sentences/voices/vr0040_frg/simpletext": _fake_ltr_bytes("Fragile"),
        }
        fake_idx = _make_fake_idx(paths)
        result = self._run_build(list(paths.keys()), fake_idx, paths)
        assert result == {"vr0010_sam": "Sam", "vr0040_frg": "Fragile"}


class TestCaching:
    """SpeakerMap caches to/from JSON."""

    def test_saves_and_loads_cache(self, tmp_path):
        """When cache_path is given, map is written and reloaded on next construction."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        b = _fake_ltr_bytes("Sam")
        fake_idx = _make_fake_idx({vp: b})
        cache_file = str(tmp_path / "speakers.json")

        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource

        def fake_read(stream, objs):
            data = stream.read()
            if data == b:
                obj = MagicMock(spec=LocalizedTextResource)
                obj.language = ["Sam"]
                objs["obj0"] = obj

        file_list = [vp]
        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read):
            smap1 = SpeakerMap(fake_idx, file_list, cache_path=cache_file)

        assert smap1.name_for("localized/voices/vr0010_sam") == "Sam"
        assert json.loads(open(cache_file).read()) == {"vr0010_sam": "Sam"}

        # Second construction uses cache, never calls read_core
        fake_idx2 = _make_fake_idx({})  # would raise KeyError if called
        smap2 = SpeakerMap(fake_idx2, file_list, cache_path=cache_file)
        assert smap2.name_for("localized/voices/vr0010_sam") == "Sam"


class TestSimpleTextFilter:
    """SpeakerMap honours a caller-supplied simpletext_filter."""

    # Helper: build a SpeakerMap without cache, patching reader so that any
    # path that reaches _build_map yields a fixed name derived from its stem.
    def _make_smap(self, file_list, fake_idx, simpletext_filter=None):
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap
        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource

        def fake_read_objects(stream, objs):
            data = stream.read()
            # stem name is encoded as ASCII bytes by _fake_ltr_bytes()
            try:
                name = data.decode("ascii")
            except Exception:
                return
            obj = MagicMock(spec=LocalizedTextResource)
            obj.language = [name]
            objs["obj0"] = obj

        kwargs = {"cache_path": ""}  # disable disk cache
        if simpletext_filter is not None:
            kwargs["simpletext_filter"] = simpletext_filter

        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read_objects):
            return SpeakerMap(fake_idx, file_list, **kwargs)

    def test_default_none_reproduces_ds_selection(self):
        """Passing simpletext_filter=None (default) selects the same paths as the
        hard-coded DS predicate: paths containing 'sentences/voices/' that end with
        '/simpletext'."""
        ds_path = "localized/sentences/voices/vr0010_sam/simpletext"
        other_path = "localized/other/voices/vr0010_sam/simpletext"  # no 'sentences/voices/'
        file_list = [ds_path, other_path]
        core_map = {
            ds_path: _fake_ltr_bytes("Sam"),
            other_path: _fake_ltr_bytes("ShouldNotAppear"),
        }
        fake_idx = _make_fake_idx(core_map)
        smap = self._make_smap(file_list, fake_idx, simpletext_filter=None)
        # DS path must be resolved; the non-matching path must be absent.
        assert smap.name_for("vr0010_sam") == "Sam"
        assert len(smap) == 1

    def test_custom_filter_selects_different_paths(self):
        """A caller-supplied filter that matches a different path convention is
        honored — the hard-coded DS predicate is NOT used."""
        hzd_path = "localized/voices_hzd/vr0010_aloy/simpletext"
        ds_path = "localized/sentences/voices/vr0010_sam/simpletext"
        file_list = [hzd_path, ds_path]
        core_map = {
            hzd_path: _fake_ltr_bytes("Aloy"),
            ds_path: _fake_ltr_bytes("Sam"),
        }
        fake_idx = _make_fake_idx(core_map)

        # Filter that matches only the HZD-style path (no 'sentences/voices/')
        hzd_filter = lambda p: "voices_hzd/" in p and p.strip().endswith("/simpletext")
        smap = self._make_smap(file_list, fake_idx, simpletext_filter=hzd_filter)

        # Only the HZD path should be in the map; DS path must be absent.
        assert smap.name_for("vr0010_aloy") == "Aloy"
        assert smap.name_for("vr0010_sam") == ""
        assert len(smap) == 1

    def test_custom_filter_none_predicate_yields_empty_map(self):
        """A filter that rejects everything yields an empty map regardless of file list."""
        ds_path = "localized/sentences/voices/vr0010_sam/simpletext"
        file_list = [ds_path]
        core_map = {ds_path: _fake_ltr_bytes("Sam")}
        fake_idx = _make_fake_idx(core_map)

        reject_all = lambda p: False
        smap = self._make_smap(file_list, fake_idx, simpletext_filter=reject_all)
        assert len(smap) == 0
