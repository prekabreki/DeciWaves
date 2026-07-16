---
description: How to cut a DeciWaves release — tag v* triggers OIDC publish to PyPI, no API token exists
type: workflow
---

# Releasing DeciWaves

The repo is **public** (`github.com/prekabreki/DeciWaves`) and ships to **PyPI as `deciwaves`**.
Releases are automated by `.github/workflows/release.yml`:

1. Bump `version` in `pyproject.toml`.
2. Push an annotated tag `vX.Y.Z` (workflow trigger is `on: push: tags: ["v*"]`).
3. `release` runs `test.yml` (ruff + pytest) then, only if green, `publish`: builds the
   pure-Python `py3-none-any` wheel + sdist on `ubuntu-latest` and uploads via **PyPI Trusted
   Publishing (OIDC)** (`pypa/gh-action-pypi-publish`, `id-token: write`).

**There is no PyPI API token — do not hunt for a `PYPI_API_TOKEN` secret.** Auth is OIDC
against a pre-registered PyPI trusted publisher (project `deciwaves`, owner `prekabreki`, repo
`DeciWaves`, workflow `release.yml`, no environment). First release **v0.1.0 shipped 2026-07-17**
this way (the repo was flipped public the same day).

Gotchas:
- `main` has **no branch protection**. The `qlty check` PR status is advisory and currently
  errors ("Build errored") — non-blocking, don't chase it (tracked in issue #60). The real gate
  is the `test` workflow.
- Keep the README install block (`pip install deciwaves`) accurate to what's actually published.
- See [[toolchain-notes]] for the runtime decoder tools (fetched by `deciwaves setup`, not part
  of the package).
