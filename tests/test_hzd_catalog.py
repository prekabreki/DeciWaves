"""HZD identification pipeline: classification + profile (pure, no install needed)."""
from deciwaves.games.hzd.catalog import classify_hzd, select_sentence_cores
from deciwaves.games.hzd.profile import build_profile, HZD_FAMILY_PREFIXES
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

    cores_sidecar = tmp_path / "catalog-cores.txt"
    rc = catalog_mod.main([
        "--package", "FAKE_PKG",
        "--out", str(tmp_path / "catalog.csv"),
        "--errors", str(tmp_path / "catalog-errors.log"),
        "--processed", str(tmp_path / "catalog-processed.txt"),
        "--cores-out", str(cores_sidecar),
    ])
    assert rc == 0
    assert read_core_paths_sidecar(str(cores_sidecar)) == [
        "localized/sentences/mq/scene/sentences"
    ]
