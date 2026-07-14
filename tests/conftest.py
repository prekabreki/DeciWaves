import os
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]

FIXTURE_PR201 = REPO / "out" / "lines_pr201.core"
FIXTURE_CUTSCENE = REPO / "out" / "sq_cs04_s01650.core"
FIXTURE_HZD_NAMINGCEREMONY = REPO / "out" / "hzd" / "mq010_cut_namingceremony.core"

# DS:DC install — integration tests skip when absent. Override with DECIWAVES_DS_INSTALL.
INSTALL_ROOT = Path(os.environ.get(
    "DECIWAVES_DS_INSTALL",
    r"C:\Program Files (x86)\Steam\steamapps\common\DEATH STRANDING DIRECTORS CUT"))
DATA_DIR = INSTALL_ROOT / "data"
OODLE_DLL = INSTALL_ROOT / "oo2core_7_win64.dll"

# Horizon Forbidden West CE install — set DECIWAVES_FW_INSTALL to enable FW integration tests.
FW_INSTALL_ROOT = Path(os.environ.get("DECIWAVES_FW_INSTALL", r"\\nonexistent"))
FW_PACKAGE_DIR = FW_INSTALL_ROOT / "LocalCacheWinGame" / "package"
FW_STREAMING_GRAPH = FW_PACKAGE_DIR / "streaming_graph.core"


@pytest.fixture(scope="session", autouse=True)
def _ds_mode():
    import deciwaves._vendor.pydecima.reader as reader
    reader.set_globals(_decima_version="DSPC")


# Core fixtures live under out/ (gitignored, derived from the install). Skip
# rather than error when absent -- regenerate on the install machine with
# `./.venv/Scripts/python.exe tools/regenerate-fixtures.py`.
@pytest.fixture
def pr201_core_bytes():
    if not FIXTURE_PR201.is_file():
        pytest.skip(f"fixture absent: {FIXTURE_PR201} (regenerate from install)")
    return FIXTURE_PR201.read_bytes()


@pytest.fixture
def cutscene_core_bytes():
    if not FIXTURE_CUTSCENE.is_file():
        pytest.skip(f"fixture absent: {FIXTURE_CUTSCENE} (regenerate from install)")
    return FIXTURE_CUTSCENE.read_bytes()


@pytest.fixture
def hzd_namingceremony_core_bytes():
    # HZD Remastered cutscene core (FW package format). Gitignored under out/hzd/;
    # regenerate with tools/regenerate-fixtures.py on a machine with the HZDR install.
    if not FIXTURE_HZD_NAMINGCEREMONY.is_file():
        pytest.skip(f"fixture absent: {FIXTURE_HZD_NAMINGCEREMONY} (regenerate from install)")
    return FIXTURE_HZD_NAMINGCEREMONY.read_bytes()


@pytest.fixture
def require_install():
    if not DATA_DIR.is_dir() or not OODLE_DLL.is_file():
        pytest.skip("DS:DC install not present")
    return INSTALL_ROOT


@pytest.fixture
def fw_package_dir():
    if not FW_PACKAGE_DIR.is_dir():
        pytest.skip("Forbidden West install not present")
    return FW_PACKAGE_DIR


@pytest.fixture
def fw_streaming_graph_bytes():
    if not FW_STREAMING_GRAPH.is_file():
        pytest.skip("Forbidden West install not present")
    return FW_STREAMING_GRAPH.read_bytes()
