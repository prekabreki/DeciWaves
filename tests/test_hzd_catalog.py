"""HZD identification pipeline: classification + profile (pure, no install needed)."""
from deciwaves.games.hzd import catalog
from deciwaves.games.hzd.catalog import classify_hzd, select_sentence_cores
from deciwaves.games.hzd.profile import build_profile, hzd_package_error, HZD_FAMILY_PREFIXES
from deciwaves.engine.catalog_io import read_core_paths_sidecar


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
    """Stand-in for FwPackage: read_core returns fixed bytes regardless of path;
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
                         lambda fw, sample_cap=None: harvested)
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw", lambda core_bytes, on_line_error=None: [])

    # catalog.main() now validates --package up front (issue #34), so the fake
    # package must look like a real LocalCacheDX12\package dir.
    fake_pkg = tmp_path / "package"
    fake_pkg.mkdir()
    (fake_pkg / "PackFileLocators.bin").write_bytes(b"x")

    cores_sidecar = tmp_path / "catalog-cores.txt"
    rc = catalog_mod.main([
        "--package", str(fake_pkg),
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(tmp_path / "catalog-errors.log"),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
    ])
    assert rc == 0
    assert read_core_paths_sidecar(str(cores_sidecar)) == [
        "localized/sentences/mq/scene/sentences"
    ]


def test_catalog_main_accepts_bare_filename_out(tmp_path, monkeypatch):
    """A bare filename (no directory component) --out must not crash: os.makedirs on
    an empty dirname raises FileNotFoundError unless the path is abspath'd first."""
    import deciwaves.games.hzd.profile as profile_mod
    import deciwaves.games.hzd.inventory as inventory_mod
    from deciwaves.games.hzd import catalog as catalog_mod

    reader = _FakeReader()
    monkeypatch.setattr(profile_mod, "build_profile", lambda package: _FakeProfile(reader))
    monkeypatch.setattr(inventory_mod, "harvest_sentence_cores", lambda fw, sample_cap=None: [])
    monkeypatch.setattr(catalog_mod, "parse_sentences_fw", lambda core_bytes, on_line_error=None: [])

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
# from fw_locators.py (issue #34). Mirrors games.fw.subtitle_bind.types_json_error.
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


def test_catalog_main_missing_package_fails_actionably(tmp_path, monkeypatch, capsys):
    # The observed bug (issue #34): `hzd run`/`hzd catalog --package <install root>`
    # used to die with a raw FileNotFoundError traceback from fw_locators.py. It
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
