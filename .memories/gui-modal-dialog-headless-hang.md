---
description: A Qt modal dialog (QMessageBox.question/exec) reachable from a teardown path hangs headless pytest-qt CI forever — no per-test timeout means it burns ~4-6h before the runner kills it
type: gotcha
---

# GUI modal dialogs hang headless CI (the #116 closeEvent incident)

A modal `QMessageBox.question(...)` (or any `exec()`/`exec_()` dialog) opened from
GUI code that a **test can reach at teardown** blocks *forever* under
`QT_QPA_PLATFORM=offscreen` — there is no user to click Yes/No and no event loop
pumping to dismiss it. It is the one call with **no built-in timeout** (unlike
`waitForFinished(ms)` / `QThreadPool.waitForDone(ms)`, which are bounded).

**Live incident (2026-07-21).** PR #172 (Close #116) added `MainWindow.closeEvent`
that popped a modal "A job is running — quit anyway?" whenever `runner.is_running`
or `dump.is_running`. Pre-existing tests
`tests/gui/test_export.py::test_shell_dump_running_blocks_pipeline_start` /
`…_export_mp3` set `w.dump._running = True` and **never reset it**, so pytest-qt's
`qtbot.addWidget(w)` teardown called `close()` → `closeEvent` → the modal → hang.
The suite wedged at test #64 (`pytest tests/gui/` exit 124). #172's *own* new
closeEvent tests passed only because they monkeypatched the dialog — they didn't
cover the OTHER tests that leave a runner "running."

**Why it was so costly.** There is **no `pytest-timeout`** in the suite, so the
hang ran ~4-6h per CI run instead of failing in seconds. Worse, #172 merged onto
`main` while its own CI was still hanging (the `test` check wasn't a hard gate),
so **every subsequent PR inherited a red base** — #174/#175/#177/#178 all "failed"
CI purely from the poisoned base, not their own diffs. Diagnosis required local
repro (`QT_QPA_PLATFORM=offscreen pytest tests/gui/ -v`, watch the last PASSED line)
because `-q` buffers dots and shows nothing before the kill. Resolved by reverting
#172 (#179); #116 reopened for a headless-safe redo.

**Preventions (do these):**

1. Add `pytest-timeout` to the test extras + `--timeout=60 --timeout-method=thread`
   in `[tool.pytest.ini_options]`. Turns any hang into a 60s failure with a
   traceback at the offending test. (An executor even tried `--timeout=120` once —
   the plugin just wasn't installed.)
2. Add `timeout-minutes: 15` to the `test` job in `.github/workflows/test.yml` so a
   hang can never burn hours of runner again.
3. Make `test` a **required** status check + "require branches up to date" — a red
   `main` then can't happen, and stale executor branches re-run against current
   main before merge.
4. Autouse fixture that monkeypatches `QMessageBox.question/warning/critical` to a
   default AND fails on any unexpected modal — catches this bug class at the source.
   Tracked as the "headless-modal-guard fixture" issue.
5. Never open an unguarded modal in a teardown-reachable path; gate on
   `QT_QPA_PLATFORM == "offscreen"` or route through an injectable confirm helper.
   Tests that simulate a running runner (`_running = True`) must reset it, or the
   `_mainwindow` fixture must clear runner/dump state before teardown `close()`.

Foreman lesson: closeEvent / threading / subprocess / modal PRs are **danger
zones** — exercise the full `pytest tests/gui/` headless before merge, never trust
a green-looking check. See [[worktree-editable-install-contamination]] for the
related "don't trust self-reported greens" rule.
