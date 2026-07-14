"""HZD identification pipeline: classification + profile (pure, no install needed)."""
from deciwaves.games.hzd.catalog import classify_hzd, select_sentence_cores
from deciwaves.games.hzd.profile import build_profile


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


# --- #43: short quest codes (mq/sq/ec/dlc) must anchor on a word boundary so they
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
    assert p.name == "hzd"
    assert p.out_dir == "out/hzd"
    assert p.transcript_path.endswith("zero_dawn_gamescript.md")
    assert p.pack_reader is None  # None when package_dir not given
