"""GUI test setup (#67): force offscreen Qt so pytest-qt runs headless in CI and
locally. Set before any QApplication is constructed. The Qt tests themselves guard on
`pytest.importorskip("PySide6")`; the pure tests here (test_cli_command,
test_entry_dispatch) must still run on a base install, so this dir is NOT skipped
wholesale."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
