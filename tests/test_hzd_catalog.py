"""HZD identification pipeline: classification + profile (pure, no install needed)."""
import csv
from deciwaves.games.hzd import catalog
from deciwaves.games.hzd.catalog import classify_hzd, select_sentence_cores
from deciwaves.games.hzd.profile import (
    build_profile, hzd_package_error, HZD_FAMILY_PREFIXES,
    cores_sidecar_header, locators_fingerprint,
)
from deciwaves.engine.catalog_io import (
    read_core_paths_sidecar, read_core_paths_sidecar_header, write_core_paths_sidecar,
)


# --- classify_hzd: (category, scene) from a sentence-core virtual path ---

def test_classify_main_quest():
    assert classify_hzd(
        "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences"
    ) == ("main_quest", "mq01_papooserider/mq010_cut_namingceremony")


def test_classify_dlc():
    assert classify_hzd(
        "localized/sentences/dlc1_test/launchtrailervo/sentences"
    ) == ("dlc", "dlc1_test/launchtrailervo")


def test_classify_collectible():
    assert classify_hzd(
        "localized/sentences/collectables_vantages/vantage01/sentences"
    ) == ("collectible", "collectables_vantages/vantage01")


def test_classify_side_quest():
    assert classify_hzd(
        "localized/sentences/sq_grave_hoard/sq_intro/sentences"
    ) == ("side_quest", "sq_grave_hoard/sq_intro")


def test_classify_aigenerated_is_ambient():
    assert classify_hzd(
        "localized/sentences/aigenerated/eclipsecultist/sentences"
    ) == ("ambient", "aigenerated/eclipsecultist")


def test_classify_unknown_family_is_other():
    assert classify_hzd(
        "localized/sentences/zzz_mystery/scene/sentences"
    ) == ("other", "zzz_mystery/scene")


# --- short quest codes (mq/sq/ec/dlc) must anchor on a word boundary so they
#          don't swallow unrelated segments that merely start with those two/three letters ---

def test_classify_eclipse_not_errand():
    """'eclipse_*' starts with 'ec' but is not an errand -- 'ec' is followed by a letter."""
    assert classify_hzd(
        "localized/sentences/eclipse_arena/fight01/sentences"
    ) == ("other", "eclipse_arena/fight01")


def test_classify_square_not_side_quest():
    """'square_*' starts with 'sq' but is not a side quest."""
    assert classify_hzd(
        "localized/sentences/square_x/scene/sentences"
    ) == ("other", "square_x/scene")


def test_classify_mqueen_not_main_quest():
    """'mqueen_*' starts with 'mq' but is not a main quest."""
    assert classify_hzd(
        "localized/sentences/mqueen_x/scene/sentences"
    ) == ("other", "mqueen_x/scene")


def test_classify_errand_boundary_still_matches():
    """A genuine 'ec' errand (code followed by a non-letter) still classifies."""
    assert classify_hzd(
        "localized/sentences/ec_the_engagement/scene/sentences"
    ) == ("errand", "ec_the_engagement/scene")


def test_classify_dlc_digit_boundary_still_matches():
    """Real DLC segments are 'dlc' + digit ('dlc1_bc08'); digit is a valid boundary."""
    assert classify_hzd(
        "localized/sentences/dlc1_bc08/scene/sentences"
    ) == ("dlc", "dlc1_bc08/scene")


def test_classify_collectable_substring_prefix_preserved():
    """'collectab' is intentionally a substring prefix of 'collectables' -- word-stem
    prefixes keep plain startswith matching (must not be boundary-anchored)."""
    assert classify_hzd(
        "localized/sentences/collectables_vantages/vantage01/sentences"
    ) == ("collectible", "collectables_vantages/vantage01")


# --- select_sentence_cores: keep dialogue sentences, drop voice simpletext ---

def test_select_keeps_sentences_drops_voices_and_simpletext():
    harvested = [
        "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences",
        "localized/sentences/voices/cultist_leader/simpletext",   # speaker, not a line core
        "localized/sentences/dlc1_test/launchtrailervo/sentences",
        "localized/sentences/some/scene/simpletext",              # any simpletext excluded
    ]
    assert select_sentence_cores(harvested) == [
        "localized/sentences/dlc1_test/launchtrailervo/sentences",
        "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences",
    ]


# --- profile ---

def test_build_profile_fields():
    p = build_profile(package_dir=None)
    assert p.decima_version == "HZDR"
    assert p.core_prefixes == HZD_FAMILY_PREFIXES
    assert p.pack_reader is None  # None when package_dir not given


# --- catalog.main() persists a core-path sidecar (issue #31): wem-metadata reuses
#          this instead of repeating catalog's own full-pack harvest ---

class _FakeReader:
    """Stand-in for HzdPackage: read_core returns fixed bytes regardless of path;
    parse_sentences_fw is monkeypatched below, so the bytes' content never matters."""
    def read_core(self, path):
        return b"CORE_BYTES"


class _FakeProfile:
    def __init__(self, reader):
        self.pack_reader = reader


def test_catalog_main_writes_cores_sidecar_with_dialogue_only_paths(tmp_path, monkeypatch):
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    harvested = [
        "localized/sentences/mq/scene/sentences",
        "localized/sentences/voices/aloy/simpletext",  # must be dropped from the sidecar
    ]
    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: harvested)
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    # catalog.main() now validates --package up front (issue #34), so the fake
    # package must look like a real LocalCacheDX12\package dir.
    fake_pkg = tmp_path / "package"
    fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    errors_log = tmp_path / "catalog-errors.log"
    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(errors_log),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
    ])
    assert rc == 0
    # happy-path proof: parse_sentences_fw's fake must match main()'s real call
    # signature (core_path=...) and actually succeed, not fail-soft into errors_log.
    assert errors_log.read_text(encoding="utf-8") == ""
    assert read_core_paths_sidecar(str(cores_sidecar)) == [
        "localized/sentences/mq/scene/sentences"
    ]


def test_catalog_main_sample_cap_leaves_existing_cores_sidecar_untouched(tmp_path, monkeypatch, capsys):
    """Finding 6: a --sample-cap'd (smoke-test) harvest is a TRUNCATED core list.
    Overwriting the shared catalog-cores.txt with it poisons wem-metadata, which
    trusts the sidecar and ignores its own --sample-cap -- silently rewriting
    wem-metadata.csv down to the capped subset. A capped run must NOT touch the
    sidecar and must say so; an existing sidecar stays byte-identical."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: ["localized/sentences/capped/scene/sentences"])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    cores_sidecar.write_text("localized/sentences/full/run/sentences\n", encoding="utf-8")
    before = cores_sidecar.read_bytes()

    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(tmp_path / "catalog-errors.log"),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
        "--sample-cap", "5",
    ])
    assert rc == 0
    assert cores_sidecar.read_bytes() == before, "capped run must not overwrite the shared sidecar"
    printed = capsys.readouterr().out.lower()
    assert "sample-cap active" in printed
    # happy-path proof: the one core actually parsed (0 failed), not fail-soft'd by a
    # TypeError from a fake signature mismatched with main()'s real call.
    assert "0 failed" in printed


def test_catalog_main_uncapped_still_writes_cores_sidecar(tmp_path, monkeypatch):
    """The complement: an uncapped run (--sample-cap 0, the default) is a full
    harvest and still writes the sidecar for wem-metadata to reuse."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: ["localized/sentences/full/scene/sentences"])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    errors_log = tmp_path / "catalog-errors.log"
    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(errors_log),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
    ])
    assert rc == 0
    # happy-path proof: the core actually parses (fail-soft would leave this empty too,
    # but errors_log being empty rules out the TypeError-and-swallow failure mode).
    assert errors_log.read_text(encoding="utf-8") == ""
    assert read_core_paths_sidecar(str(cores_sidecar)) == ["localized/sentences/full/scene/sentences"]


def test_catalog_main_records_harvest_read_failures(tmp_path, monkeypatch, capsys):
    """Issue #66: cores whose body read fails during the harvest content-scan must be
    recorded (errors log) and counted in the end-of-run summary -- not dropped silently
    (the one drop the GUI issues panel couldn't otherwise see, spec §5.4)."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    def fake_harvest(fw, sample_cap=None, on_read_error=None):
        # simulate two unreadable cores surfaced via the callback the harvester exposes
        if on_read_error is not None:
            on_read_error(0x1111, OSError("boom-a"))
            on_read_error(0x2222, ValueError("boom-b"))
        return ["localized/sentences/mq/scene/sentences"]

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores", fake_harvest)
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                        lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    errors_log = tmp_path / "catalog-errors.log"
    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(errors_log),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(tmp_path / "catalog-cores.txt"),
    ])
    assert rc == 0
    err_text = errors_log.read_text(encoding="utf-8")
    assert "harvest:" in err_text            # tagged distinctly from per-core parse failures
    assert "boom-a" in err_text and "boom-b" in err_text
    printed = capsys.readouterr().out
    assert "2 unreadable during harvest" in printed


def test_catalog_harvest_read_failures_do_not_grow_across_resumes(tmp_path, monkeypatch, capsys):
    """A persistently-unreadable core must have exactly ONE harvest entry in
    catalog-errors.log, not one appended per resume. The harvest re-scans the whole
    pack every run (unlike the per-core loop, which skips cores already in the
    processed sidecar), so an append-mode log would otherwise duplicate the same
    'harvest:<hash>' line on every resume -- the FW-extract non-growth contract
    (test_extract_errors_log_does_not_grow_across_resumes...), applied here."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    def fake_harvest(fw, sample_cap=None, on_read_error=None):
        # the SAME core fails to read on every run (a persistent, deterministic failure)
        if on_read_error is not None:
            on_read_error(0x1111, OSError("boom-persistent"))
        return ["localized/sentences/mq/scene/sentences"]

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores", fake_harvest)
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                        lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")
    errors_log = tmp_path / "catalog-errors.log"
    argv = [
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(errors_log),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(tmp_path / "catalog-cores.txt"),
    ]

    for _ in range(3):   # first run + two resumes
        assert catalog_mod.main(argv) == 0

    harvest_lines = [ln for ln in errors_log.read_text(encoding="utf-8").splitlines()
                     if ln.startswith("harvest:")]
    assert len(harvest_lines) == 1, harvest_lines
    assert "boom-persistent" in harvest_lines[0]


def test_catalog_main_uncapped_cores_sidecar_carries_locators_header(tmp_path, monkeypatch):
    """Issue #45: an uncapped run's cores sidecar must carry a locators-fingerprint
    header wem_metadata can check for staleness against a patched pack."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: ["localized/sentences/full/scene/sentences"])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    errors_log = tmp_path / "catalog-errors.log"
    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(errors_log),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
    ])
    assert rc == 0
    # happy-path proof: no fail-soft TypeError from a mismatched fake signature.
    assert errors_log.read_text(encoding="utf-8") == ""
    assert read_core_paths_sidecar_header(str(cores_sidecar)) == cores_sidecar_header(str(fake_pkg))
    # the header line must not leak into the actual path list
    assert read_core_paths_sidecar(str(cores_sidecar)) == ["localized/sentences/full/scene/sentences"]


def test_catalog_main_sample_capped_cores_sidecar_unchanged_including_header(tmp_path, monkeypatch, capsys):
    """The sample-cap guard (finding 6) must still leave an existing header-carrying
    sidecar byte-identical -- a capped run never touches catalog-cores.txt at all."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: ["localized/sentences/capped/scene/sentences"])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    write_core_paths_sidecar(str(cores_sidecar), ["localized/sentences/full/run/sentences"],
                             header=cores_sidecar_header(str(fake_pkg)))
    before = cores_sidecar.read_bytes()

    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(tmp_path / "catalog-errors.log"),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
        "--sample-cap", "5",
    ])
    assert rc == 0
    assert cores_sidecar.read_bytes() == before
    printed = capsys.readouterr().out.lower()
    assert "sample-cap active" in printed
    # happy-path proof, as above: the capped core still actually parsed (0 failed).
    assert "0 failed" in printed


class _FakeLine:
    line_id = "L0"; line_index = 0; speaker_code = "localized/voices/aloy"
    subtitle_en = "hi"; wem_path_en = "loc/x.wem"


def test_catalog_main_resumes_after_zero_byte_out(tmp_path, monkeypatch):
    """Finding 9: a 0-byte out/hzd/catalog.csv left by a crash (created before the
    header was written) must get a real header on resume -- an is_file()-only
    'new file' check treats it as already-headered, so the first data row silently
    becomes the CSV's fieldnames on the next load. Mirrors fcc0d1c for fw."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores",
                         lambda fw, sample_cap=None, on_read_error=None: ["localized/sentences/mq/scene/sentences"])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [_FakeLine()])

    fake_pkg = tmp_path / "package"; fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    out = tmp_path / "catalog.csv"
    out.write_bytes(b"")  # 0-byte crash artifact

    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(out),
        "--errors", str(tmp_path / "catalog-errors.log"),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(tmp_path / "catalog-cores.txt"),
    ])
    assert rc == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["core_path"] == "localized/sentences/mq/scene/sentences"


def test_catalog_main_accepts_bare_filename_out(tmp_path, monkeypatch):
    """A bare filename (no directory component) --out must not crash: os.makedirs on
    an empty dirname raises FileNotFoundError unless the path is abspath'd first."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores", lambda fw, sample_cap=None, on_read_error=None: [])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw",
                         lambda core_bytes, on_line_error=None, core_path=None: [])

    fake_pkg = tmp_path / "package"
    fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", "catalog.csv",  # bare filename, no directory component
        "--errors", "catalog-errors.log",
        "--processed", "catalog-processed.txt",
        "--cores-out", "catalog-cores.txt",
    ])
    assert rc == 0
    assert (tmp_path / "catalog.csv").is_file()


# ---------------------------------------------------------------------------
# hzd_package_error: actionable failure when --package doesn't point at the
# LocalCacheDX12\package dir, instead of a bare FileNotFoundError traceback
# from hzd_locators.py (issue #34). Mirrors games.fw.subtitle_bind.types_json_error.
# ---------------------------------------------------------------------------

def test_hzd_package_error_none_when_locators_present(tmp_path):
    (tmp_path / "PackFileLocators.bin").write_bytes(b"x")
    assert hzd_package_error(str(tmp_path)) is None


def test_hzd_package_error_message_when_missing(tmp_path):
    # install-root-shaped dir: exists, but no PackFileLocators.bin inside.
    msg = hzd_package_error(str(tmp_path))
    assert msg is not None
    assert "--hzd-package" in msg
    assert "PackFileLocators.bin" in msg
    assert "LocalCacheDX12" in msg
    # ASCII-only (Windows console safety)
    msg.encode("ascii")


def test_hzd_package_error_message_when_dir_missing_entirely(tmp_path):
    msg = hzd_package_error(str(tmp_path / "does-not-exist"))
    assert msg is not None
    assert "--hzd-package" in msg
    assert "PackFileLocators.bin" in msg


# ---------------------------------------------------------------------------
# locators_fingerprint / cores_sidecar_header (issue #45): a cheap size:mtime_ns
# fingerprint of PackFileLocators.bin, stamped into catalog-cores.txt's sidecar header
# so a downstream stage (wem_metadata) can tell a post-patch pack apart from the one
# the sidecar was harvested from.
# ---------------------------------------------------------------------------

def test_locators_fingerprint_is_size_colon_mtime_ns(tmp_path):
    locators = tmp_path / "PackFileLocators.bin"
    locators.write_bytes(b"abcdef")
    st = locators.stat()
    assert locators_fingerprint(str(tmp_path)) == f"{st.st_size}:{st.st_mtime_ns}"


def test_locators_fingerprint_changes_when_locators_file_changes(tmp_path):
    locators = tmp_path / "PackFileLocators.bin"
    locators.write_bytes(b"abcdef")
    before = locators_fingerprint(str(tmp_path))
    locators.write_bytes(b"abcdef-and-more-after-a-patch")   # size changes
    after = locators_fingerprint(str(tmp_path))
    assert before != after


def test_cores_sidecar_header_is_a_comment_line_wrapping_the_fingerprint(tmp_path):
    locators = tmp_path / "PackFileLocators.bin"
    locators.write_bytes(b"abcdef")
    header = cores_sidecar_header(str(tmp_path))
    assert header.startswith("#")
    assert locators_fingerprint(str(tmp_path)) in header


def test_catalog_main_missing_package_fails_actionably(tmp_path, monkeypatch, capsys):
    # The observed bug (issue #34): `hzd run`/`hzd catalog --package <install root>`
    # used to die with a raw FileNotFoundError traceback from hzd_locators.py. It
    # must instead print an actionable message and return nonzero.
    monkeypatch.chdir(tmp_path)
    bad_package = tmp_path / "install_root"  # exists, but no PackFileLocators.bin
    bad_package.mkdir()
    rc = catalog.main(["--package", str(bad_package)])
    assert rc == 1

    captured = capsys.readouterr()
    assert "--hzd-package" in captured.out
    assert "PackFileLocators.bin" in captured.out
    assert captured.err == ""  # no traceback


# ---------------------------------------------------------------------------
# load_catalog_dict (issue #47): the shared catalog.csv -> {line_id: row} loading path
# for asr_bind.py/render.py, with loud collision counting instead of a silent
# last-write-win dict comprehension -- the guard that proves fallback-id namespacing
# actually eliminated cross-core collisions (and catches a regression if it doesn't).
# ---------------------------------------------------------------------------

def _write_catalog_csv(path, rows):
    fieldnames = ["line_id", "core_path", "line_index", "category", "scene",
                  "speaker_code", "speaker_name", "subtitle_en", "wem_path_en", "language"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in fieldnames}, **r})


def test_load_catalog_dict_no_collisions_is_silent(tmp_path, capsys):
    from deciwaves.games.hzd.catalog import load_catalog_dict

    path = tmp_path / "catalog.csv"
    _write_catalog_csv(path, [
        {"line_id": "MQ04_a", "subtitle_en": "one"},
        {"line_id": "MQ04_b", "subtitle_en": "two"},
    ])

    result = load_catalog_dict(str(path))

    assert set(result) == {"MQ04_a", "MQ04_b"}
    assert result["MQ04_a"]["subtitle_en"] == "one"
    assert "collision" not in capsys.readouterr().out.lower()


def test_load_catalog_dict_reports_collisions_loudly(tmp_path, capsys):
    """Two distinct rows sharing the same line_id (e.g. a pre-#47 workspace's
    un-namespaced sentence#N fallback ids from two different cores) must still resolve
    (last write wins, unchanged) but the collision must be counted and reported --
    never silent."""
    from deciwaves.games.hzd.catalog import load_catalog_dict

    path = tmp_path / "catalog.csv"
    _write_catalog_csv(path, [
        {"line_id": "sentence#0", "core_path": "core/a/sentences", "subtitle_en": "from core a"},
        {"line_id": "sentence#0", "core_path": "core/b/sentences", "subtitle_en": "from core b"},
        {"line_id": "MQ04_a", "core_path": "core/c/sentences", "subtitle_en": "unique"},
    ])

    result = load_catalog_dict(str(path))

    assert result["sentence#0"]["subtitle_en"] == "from core b"   # last write wins, as before
    assert result["MQ04_a"]["subtitle_en"] == "unique"
    printed = capsys.readouterr().out
    assert "1" in printed
    assert "collision" in printed.lower()


def test_load_catalog_dict_multiple_collisions_reports_exact_count(tmp_path, capsys):
    from deciwaves.games.hzd.catalog import load_catalog_dict

    path = tmp_path / "catalog.csv"
    _write_catalog_csv(path, [
        {"line_id": "X", "core_path": "1"}, {"line_id": "X", "core_path": "2"},
        {"line_id": "X", "core_path": "3"},   # 2 collisions on "X" (2nd and 3rd row)
        {"line_id": "Y", "core_path": "1"}, {"line_id": "Y", "core_path": "2"},  # 1 collision on "Y"
    ])

    load_catalog_dict(str(path))

    printed = capsys.readouterr().out
    assert "3" in printed   # 2 + 1 = 3 total collisions


# ---------------------------------------------------------------------------
# Bare pre-#47 fallback-id detection (review finding): a half-resumed pre-#47
# workspace's catalog.csv can hold OLD bare `sentence#N` ids for already-processed
# cores (catalog resumes append-only) while wem-metadata.csv is rewritten fully every
# run with NEW namespaced ids -- the join between the two on line_id silently misses
# for those rows, dropping unnamed lines from already-processed cores out of the reel.
# The line_id collision counter above never fires on this surface (it only counts
# collisions WITHIN catalog.csv), so this is a separate, loud detector.
# ---------------------------------------------------------------------------

def test_load_catalog_dict_detects_bare_pre47_fallback_ids(tmp_path, capsys):
    from deciwaves.games.hzd.catalog import load_catalog_dict

    path = tmp_path / "catalog.csv"
    _write_catalog_csv(path, [
        {"line_id": "sentence#0", "core_path": "core/a/sentences"},
        {"line_id": "sentence#5", "core_path": "core/b/sentences"},
        {"line_id": "MQ04_a", "core_path": "core/c/sentences"},
    ])

    load_catalog_dict(str(path))

    printed = capsys.readouterr().out
    assert "2" in printed
    assert "pre-#47" in printed
    assert "regenerat" in printed.lower()


def test_load_catalog_dict_namespaced_and_named_ids_report_no_bare_warning(tmp_path, capsys):
    """Proper names and NEW namespaced fallback ids (`<hash8>#sentence#N`) must never
    trip the bare-id detector -- only the un-namespaced pre-#47 form does."""
    from deciwaves.games.hzd.catalog import load_catalog_dict

    path = tmp_path / "catalog.csv"
    _write_catalog_csv(path, [
        {"line_id": "MQ04_a", "core_path": "core/a/sentences"},
        {"line_id": "a1b2c3d4#sentence#0", "core_path": "core/b/sentences"},
        {"line_id": "b2c3d4e5#sentence#1", "core_path": "core/c/sentences"},
    ])

    load_catalog_dict(str(path))

    printed = capsys.readouterr().out
    assert "pre-#47" not in printed
    assert printed == ""
