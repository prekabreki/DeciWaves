---
description: main now requires the `test` check + up-to-date branches (strict) as of 2026-07-21 (#184); foreman-status merges must serialize (update-branch → CI → merge per PR), not batch.
type: reference
---

Since 2026-07-21 (#184), `main` has GitHub branch protection:
`required_status_checks.strict = true` + `contexts = ["test"]`, `enforce_admins = false`,
no required PR reviews. (`qlty check` is intentionally left non-required / advisory.)
Verify: `gh api repos/prekabreki/DeciWaves/branches/main/protection`.

**Operational consequence for foreman-status (and any multi-PR merge):** `strict:true`
= "require branches up to date before merging". With no merge queue configured, each
merge advances `main` and **re-stales every other open PR**, even file-disjoint ones.
So a wave of N green PRs cannot be batch-merged — merges serialize:

1. Merge the one PR that is already up to date with `main`.
2. For each remaining PR: `gh pr update-branch <N>` (merges current `main` in) →
   wait for the `test` re-run to pass → `gh pr merge <N> --squash --delete-branch`.
3. Repeat. ~one CI cycle (~2 min) per PR.

A background waiter/merge-train (update-branch → poll `gh pr checks <N>` for the `test`
row == pass → merge, stop on any `fail`) automates this without babysitting. This is by
design — it's the belt to the `pytest-timeout` (#182) + job `timeout-minutes` (#183)
suspenders that stop a hung test from burning CI hours (see
[[gui-modal-dialog-headless-hang]]). `enforce_admins=false` means the owner *can*
`gh pr merge --admin`-bypass, but doing so defeats the stale-fork check #184 exists for —
don't, unless deliberately.
