"""Regenerate the gitignored test-fixture cores from the DS:DC install.

These cores live under out/ (gitignored, derived from the install), so a fresh
checkout -- or an over-eager `out/` cleanup -- leaves the fixture-based tests
skipped. Run this on a machine with the install to restore them:

    ./.venv/Scripts/python.exe tools/regenerate-fixtures.py

Override the install location with --data-dir / --oodle if non-default.
"""
import argparse
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_INSTALL = r"C:\Program Files (x86)\Steam\steamapps\common\DEATH STRANDING DIRECTORS CUT"

FIXTURES = {
    "localized/sentences/ds_lines_terminal/lines_pr201/sentences": "out/lines_pr201.core",
    "localized/sentences/ds_lines_cutscene/sq_cs04_s01650/sentences": "out/sq_cs04_s01650.core",
}

# HZD Remastered (Forbidden-West package format) — extracted via FwPackage, no Oodle/DSPC.
_HZD_PACKAGE = (r"C:\Program Files (x86)\Steam\steamapps\common"
                r"\Horizon - Zero Dawn Remastered\LocalCacheDX12\package")

HZD_FIXTURES = {
    # A real main-quest cutscene core: 32 dialogue lines, speaker + EN subtitle.
    "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences":
        "out/hzd/mq010_cut_namingceremony.core",
}


def _regen_ds(data_dir: str, oodle: str) -> None:
    import deciwaves._vendor.pydecima.reader as reader
    reader.set_globals(_decima_version="DSPC")
    from deciwaves.engine.pack.bin_index import PackIndex

    idx = PackIndex(data_dir, oodle)
    for vpath, out in FIXTURES.items():
        data = idx.read_core(vpath)
        os.makedirs(os.path.dirname(os.path.join(REPO, out)), exist_ok=True)
        with open(os.path.join(REPO, out), "wb") as f:
            f.write(data)
        print(f"restored {out}: {len(data)} bytes")


def _regen_hzd(package_dir: str) -> None:
    if not os.path.isdir(package_dir):
        print(f"skipping HZD fixtures: package dir absent ({package_dir})")
        return
    from deciwaves.engine.pack.fw_package import FwPackage

    fw = FwPackage(package_dir)
    for vpath, out in HZD_FIXTURES.items():
        data = fw.read_core(vpath)
        os.makedirs(os.path.dirname(os.path.join(REPO, out)), exist_ok=True)
        with open(os.path.join(REPO, out), "wb") as f:
            f.write(data)
        print(f"restored {out}: {len(data)} bytes")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=os.path.join(_INSTALL, "data"))
    ap.add_argument("--oodle", default=os.path.join(_INSTALL, "oo2core_7_win64.dll"))
    ap.add_argument("--hzd-package", default=_HZD_PACKAGE)
    args = ap.parse_args()

    if os.path.isdir(args.data_dir):
        _regen_ds(args.data_dir, args.oodle)
    else:
        print(f"skipping DS fixtures: data dir absent ({args.data_dir})")
    _regen_hzd(args.hzd_package)


if __name__ == "__main__":
    main()
