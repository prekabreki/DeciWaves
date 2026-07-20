---
description: Parallel git worktrees share one editable-install .pth and race over it; pytest can import the wrong worktree's src unless pyproject pins pythonpath=["src"]
type: gotcha
---

# Worktree editable-install contamination

`pip install -e .` registers deciwaves via a single, **interpreter-global**
`site-packages/__editable__.deciwaves-0.1.0.pth` whose one line is an absolute
path to exactly one `src` directory. There is one such file per interpreter —
**not** one per worktree.

So when several worktrees exist at once — foreman executors under
`.foreman-worktrees/issue-*`, or Claude Code subagents under
`.claude/worktrees/` — every `pip install -e .` rewrites that same `.pth`,
last-writer-wins. A bare `import deciwaves` from *any* worktree then resolves to
whichever worktree last won the race, not the local one. Observed live during
the 2026-07-20 foreman wave: the `.pth` flipped `issue-124` → `issue-119` →
`issue-91` mid-run, and `pytest` in `issue-54` imported `issue-91/src`. The
result: an executor's verify run tests code that isn't its own diff, so its
"How to verify — pass" claim is meaningless (false passes AND false failures).

**This is env-independent** — both the WindowsApps system Python *and* the repo
`.venv` carry their own single `.pth`, both raced. "Just run tests in `.venv`"
does not fix it.

**The fix (in `pyproject.toml`):**

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

pytest prepends each rootdir's own `src/` to `sys.path` before collection.
Each worktree is its own rootdir, so each imports its own source regardless of
what the shared `.pth` points at. Proven: with the prepend, `issue-54`'s pytest
imports `issue-54/src` even while the `.pth` still names `issue-91`.

**Corollary for review:** a foreman PR produced before this fix landed cannot be
trusted on its self-reported green — re-run its tests in a clean single-worktree
checkout. And any executor left `in-progress` with a branch but **zero commits
and no PR** has failed silently (e.g. #74 in that wave), not merely stalled.
Related: [[fw-streaming-graph]] is unaffected; this is purely a test-harness
isolation issue.
