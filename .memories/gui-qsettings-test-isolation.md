---
description: "#128's QSettings persistence makes every MainWindow() test read/write the REAL registry scope — local pytest scribbles test state into the user's actual GUI prefs; needs an autouse isolation fixture"
type: gotcha
---

# GUI tests leak into the real QSettings registry scope (post-#128)

Issue #128 (PR #195, merged 2026-07-21) gave `MainWindow.__init__` a default
`QSettings("DeciWaves", "gui")` (registry-backed on Windows) restored at construction and
saved in `closeEvent`. Consequence for the test suite: **every `MainWindow()` call site
(~33 across `tests/gui/`) now reads the user's real saved GUI state at construction, and
pytest-qt's teardown `close()` fires `closeEvent`, writing test state back into
`HKCU\Software\DeciWaves`.**

Two failure modes:

1. **Local pytest runs corrupt the user's real GUI session prefs** — after a suite run,
   the GUI opens with whatever geometry/game/workspace the last test window had.
   Recovery: delete `HKCU\Software\DeciWaves` and relaunch.
2. **Saved real prefs feed back into test init** — tests survive today only because
   nearly all of them call `set_workspace(...)` + `select_game(...)` explicitly right
   after construction, which papers over the restored state. That makes the suite
   order-dependent and latently flaky (e.g. `select_game(x)` fires no signal when the
   restored game already IS x).

**CI green proves nothing here** — runners start with an empty settings scope, so this
whole class is invisible to CI. It was caught only by diff review.

**Fix (follow-up issue): an autouse fixture in `tests/gui/conftest.py`** that forces
file-backed ini `QSettings` under `tmp_path` for every test — mirror the #180 autouse
modal-guard fixture that lives in the same conftest. #128's own round-trip test shows the
mechanism: `MainWindow(settings=QSettings(str(tmp_path/"settings.ini"), IniFormat))`.

Same lesson-family as [[gui-modal-dialog-headless-hang]]: anything reachable from
pytest-qt teardown `close()` (modals, disk/registry writes) runs on every test, whether
the test meant it or not.
