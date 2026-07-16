import os
import shutil
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


@pytest.fixture
def parsed_stage_args():
    """Call a stage's ``main(argv)`` only as far as its own
    ``ArgumentParser.parse_args`` call, then abort -- returns the resulting
    ``Namespace``.

    Lets a test assert on a stage's REAL argparse defaults (or on what
    another module's hand-built argv actually resolves to) without needing a
    real install/manifest/types.json on disk to let ``main()`` run to
    completion, and without re-declaring the stage's flags/defaults in the
    test itself -- which would just be a second copy that happens to match
    today (see issue #17's render/subtitle-bind default-drift bugs, which
    this pattern is meant to make impossible to reintroduce silently).

    The ``ArgumentParser.parse_args`` patch is scoped tightly around each
    individual call (via ``pytest.MonkeyPatch.context()``), not the whole
    test -- a caller like ``deciwaves fw run`` does its OWN argparse
    parsing before ever reaching the nested stage's ``main()``, and that
    outer parse must not be intercepted too.
    """
    import argparse

    class _ParsedEarly(Exception):
        def __init__(self, ns):
            self.ns = ns

    real_parse_args = argparse.ArgumentParser.parse_args

    def _spy(self, args=None, namespace=None):
        raise _ParsedEarly(real_parse_args(self, args, namespace))

    def _run(main_fn, argv):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(argparse.ArgumentParser, "parse_args", _spy)
            try:
                main_fn(argv)
            except _ParsedEarly as exc:
                return exc.ns
        raise AssertionError(f"{main_fn} never reached ArgumentParser.parse_args")

    return _run


# Shared by test_audio_clip.py and test_render_story.py -- both gate real-ffmpeg
# tests on the same two binaries; this used to be copy-pasted in each file.
needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed")


def catalog_row(**kw):
    """Minimal in-scope, non-cutscene catalog row (DS catalog.csv shape). Shared
    by test_selection.py and test_story_order.py, which both build the same
    row shape under the (unrelated) name `_row()`."""
    base = dict(
        line_id="id",
        core_path="c",
        line_index="0",
        category="terminal",
        scene="lines_pr201",
        speaker_code="",
        speaker_name="The Engineer",
        subtitle_en="Hello there friend.",
        wem_path_en="loc/x.wem.english",
        language="english",
    )
    base.update(kw)
    return base
