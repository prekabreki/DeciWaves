# tests/test_speakers.py
"""TDD tests for SpeakerMap."""
from unittest.mock import MagicMock, patch
import json
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


def _run_build_with_language_list(vp, language_list):
    """Build a SpeakerMap from a single fake resource whose LocalizedTextResource.language
    is exactly `language_list` -- shared by TestEnglishSelectionGuard and
    TestSiblingSlotRecovery, both of which drive the same fake-reader plumbing with
    different language-list shapes."""
    import deciwaves._vendor.pydecima.reader as reader
    from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
    from deciwaves.engine.speakers import SpeakerMap

    fake_idx = _make_fake_idx({vp: b"data"})

    def fake_read(stream, objs):
        obj = MagicMock(spec=LocalizedTextResource)
        obj.language = language_list
        objs["obj0"] = obj

    with patch.object(reader, "read_objects_from_stream", side_effect=fake_read):
        return SpeakerMap._build_map(fake_idx, [vp])


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


class TestEnglishSelectionGuard:
    """Issue #3: the vendored DSPC scanner skips EMPTY language slots and
    pads only at the end of the list, so when a resource's English slot is
    empty, index 0 silently lands on the first non-empty language (usually
    Japanese) instead. ``_build_map`` must reject non-Latin text at index 0
    and fall back to a stem-derived name rather than surface it."""

    JAPANESE_ONLY = "サム"  # Katakana "Samu" -- stands in for a
    # resource whose English slot was empty and index 0 shifted to Japanese.

    def test_full_language_list_index0_english_accepted(self):
        """A full, realistic language list with a plausibly-English string at
        index 0 is accepted exactly as before -- the happy path is untouched."""
        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        language_list = ["Sam", "Sam (French)", self.JAPANESE_ONLY] + [""] * 18
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0010_sam": "Sam"}

    def test_empty_english_shift_uses_stem_fallback_not_japanese(self):
        """The bug: English slot was empty, so index 0 is Japanese text. Must
        NOT surface the Japanese text -- must fall back to a stem-derived name."""
        vp = "localized/sentences/voices/vr0099_mystery_person/simpletext"
        language_list = [self.JAPANESE_ONLY] + [""] * 20
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0099_mystery_person": "Mystery Person"}
        assert self.JAPANESE_ONLY not in result.values()

    def test_all_empty_string_slots_existing_fallback_unchanged(self):
        """A non-empty language list where every slot is an empty string is
        the pre-existing "no text at all" case: leave it unmapped (name_for()
        falls back to ""), same as the empty-list case already covered by
        test_empty_language_list_skipped."""
        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        language_list = [""] * 21
        result = _run_build_with_language_list(vp, language_list)
        assert result == {}

    def test_index0_english_accepted_ignores_different_sibling_names(self):
        """T6b: happy path unchanged -- when index 0 passes the guard,
        sibling slots are never consulted, even if they carry a different
        plausible name."""
        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        language_list = ["Sam", "NotSam", self.JAPANESE_ONLY] + [""] * 18
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0010_sam": "Sam"}


class TestSiblingSlotRecovery:
    """T6b (issue #3 follow-up): in the shift case (index 0 rejected by
    ``is_plausibly_english``), character display names are frequently
    identical Latin text across locales, so scan the remaining language
    slots in order for the first non-empty, plausibly-English candidate
    before giving up and falling back to the stem-derived guess."""

    JAPANESE_ONLY = "サム"  # stands in for a shifted, non-English index 0.

    def test_shift_case_uses_first_latin_sibling_slot(self):
        """Shift case (index 0 rejected): a later slot with a plausibly-
        English name ("Fragile") is used instead of the stem guess ("Frg")."""
        vp = "localized/sentences/voices/vr0040_frg/simpletext"
        language_list = [self.JAPANESE_ONLY, "Fragile"] + [""] * 19
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0040_frg": "Fragile"}

    def test_shift_case_picks_first_qualifying_sibling_in_order(self):
        """When multiple sibling slots qualify, the first one (in list
        order) wins."""
        vp = "localized/sentences/voices/vr0040_frg/simpletext"
        language_list = [self.JAPANESE_ONLY, "", "Fragile", "AlsoFragile"] + [""] * 17
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0040_frg": "Fragile"}

    def test_shift_case_all_siblings_non_latin_or_empty_falls_back_to_stem(self):
        """Shift case where every remaining slot is also non-Latin or
        empty: no sibling candidate qualifies, so fall back to the
        stem-derived guess exactly as before this change."""
        vp = "localized/sentences/voices/vr0099_mystery_person/simpletext"
        language_list = [self.JAPANESE_ONLY, self.JAPANESE_ONLY, ""] + [""] * 18
        result = _run_build_with_language_list(vp, language_list)
        assert result == {"vr0099_mystery_person": "Mystery Person"}


class TestNameFromStem:
    """Direct unit tests pinning the stem-derived fallback name contract."""

    def test_strips_vr_prefix_and_title_cases(self):
        from deciwaves.engine.speakers import _name_from_stem
        assert _name_from_stem("vr0010_sam") == "Sam"

    def test_multi_word_slug(self):
        from deciwaves.engine.speakers import _name_from_stem
        assert _name_from_stem("vr0099_mystery_person") == "Mystery Person"

    def test_no_recognizable_prefix_falls_back_to_whole_stem(self):
        from deciwaves.engine.speakers import _name_from_stem
        assert _name_from_stem("weird_stem_noprefix") == "Weird Stem Noprefix"


class TestCaching:
    """SpeakerMap caches to/from JSON.

    The cache is versioned (issue #3): it is loaded unconditionally when
    present, so any fix to _build_map's selection logic must be paired with
    a schema marker that forces regeneration of stale on-disk caches --
    otherwise existing workspaces keep serving the pre-fix (Japanese) names
    forever.
    """

    def test_saves_and_loads_cache(self, tmp_path):
        """When cache_path is given, map is written (versioned) and reloaded
        on next construction."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap, _SCHEMA_VERSION

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
        on_disk = json.loads(open(cache_file).read())
        assert on_disk == {"schema_version": _SCHEMA_VERSION, "speakers": {"vr0010_sam": "Sam"}}

        # Second construction uses cache, never calls read_core
        fake_idx2 = _make_fake_idx({})  # would raise KeyError if called
        smap2 = SpeakerMap(fake_idx2, file_list, cache_path=cache_file)
        assert smap2.name_for("localized/voices/vr0010_sam") == "Sam"

    def test_old_unversioned_format_ignored_and_regenerated(self, tmp_path):
        """A pre-fix, unversioned cache (a flat {stem: name} dict, possibly
        carrying a stale Japanese name from the bug) must be ignored, not
        loaded -- and the map rebuilt from the real source."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap, _SCHEMA_VERSION
        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        b = _fake_ltr_bytes("Sam")
        cache_file = tmp_path / "speakers.json"
        # Old unversioned format: flat dict, no "schema_version"/"speakers" wrapper.
        cache_file.write_text(json.dumps({"vr0010_sam": "STALE-JAPANESE-NAME"}), encoding="utf-8")

        fake_idx = _make_fake_idx({vp: b})

        def fake_read(stream, objs):
            if stream.read() == b:
                obj = MagicMock(spec=LocalizedTextResource)
                obj.language = ["Sam"]
                objs["obj0"] = obj

        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read):
            smap = SpeakerMap(fake_idx, [vp], cache_path=str(cache_file))

        assert smap.name_for("localized/voices/vr0010_sam") == "Sam"
        # Regeneration also rewrites the cache file to the new, versioned format.
        rewritten = json.loads(cache_file.read_text(encoding="utf-8"))
        assert rewritten == {"schema_version": _SCHEMA_VERSION, "speakers": {"vr0010_sam": "Sam"}}

    def test_stale_schema_version_ignored_and_regenerated(self, tmp_path):
        """A versioned cache with an older schema_version is also regenerated,
        not just a fully-unversioned one."""
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves.engine.speakers import SpeakerMap, _SCHEMA_VERSION
        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource

        vp = "localized/sentences/voices/vr0010_sam/simpletext"
        b = _fake_ltr_bytes("Sam")
        cache_file = tmp_path / "speakers.json"
        cache_file.write_text(
            json.dumps({"schema_version": _SCHEMA_VERSION - 1, "speakers": {"vr0010_sam": "STALE"}}),
            encoding="utf-8",
        )

        fake_idx = _make_fake_idx({vp: b})

        def fake_read(stream, objs):
            if stream.read() == b:
                obj = MagicMock(spec=LocalizedTextResource)
                obj.language = ["Sam"]
                objs["obj0"] = obj

        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read):
            smap = SpeakerMap(fake_idx, [vp], cache_path=str(cache_file))

        assert smap.name_for("localized/voices/vr0010_sam") == "Sam"

    def test_current_versioned_format_loaded_without_rebuild(self, tmp_path):
        """A cache already in the current versioned format is loaded as-is
        (no rebuild) -- read_core is never called."""
        from deciwaves.engine.speakers import SpeakerMap, _SCHEMA_VERSION

        cache_file = tmp_path / "speakers.json"
        cache_file.write_text(
            json.dumps({"schema_version": _SCHEMA_VERSION, "speakers": {"vr0010_sam": "Sam"}}),
            encoding="utf-8",
        )

        fake_idx = _make_fake_idx({})  # would raise KeyError if read_core is called
        smap = SpeakerMap(fake_idx, [], cache_path=str(cache_file))
        assert smap.name_for("localized/voices/vr0010_sam") == "Sam"


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


class TestPackagedFileListSimpletextPaths:
    """The bundled ds/data-file-list.txt (Task 18) carries the voice simpletext
    paths SpeakerMap needs, alongside the dialogue sentence cores, so an
    out-of-box run derives speaker names live from the user's own install
    (no bundled name content)."""

    def test_packaged_file_list_simpletext_paths_are_picked_up(self):
        from deciwaves import data
        from deciwaves.engine.speakers import SpeakerMap, _DS_SIMPLETEXT_FILTER
        import deciwaves._vendor.pydecima.reader as reader
        from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource

        file_list = data.packaged("ds/data-file-list.txt").read_text(encoding="utf-8").splitlines()
        simpletext_paths = [p for p in file_list if _DS_SIMPLETEXT_FILTER(p)]
        assert len(simpletext_paths) == 96

        # Stub the install: every simpletext core "exists" and decodes to a name
        # derived deterministically from its own stem (content doesn't matter —
        # only that the path was read and dispatched through the real filter).
        core_map = {vp: vp.encode("ascii") for vp in simpletext_paths}
        fake_idx = _make_fake_idx(core_map)

        def fake_read_objects(stream, objs):
            vp = stream.read().decode("ascii")
            stem = vp.rstrip("/").split("/")[-2]
            obj = MagicMock(spec=LocalizedTextResource)
            obj.language = [stem]
            objs["obj0"] = obj

        with patch.object(reader, "read_objects_from_stream", side_effect=fake_read_objects):
            smap = SpeakerMap(fake_idx, file_list, cache_path="")

        assert len(smap) == 96
        assert smap.name_for("localized/voices/vr0010_sam") == "vr0010_sam"
