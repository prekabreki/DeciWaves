---
description: The GUI's ASR/GPU install hint must be two steps, PowerShell-prefixed, absolute-path — three separate footguns
type: gui
---

# ASR / GPU install command: three footguns the hint must avoid

`src/deciwaves/gui/gpu_probe.py::build_asr_install_steps` builds the copy-pasteable
install command shown in `AsrInstallHint`. Dogfooding (2026-07-22) surfaced three
independent ways the naive command fails for a real first-time user:

1. **Two steps, not one.** `--index-url https://download.pytorch.org/whl/cuXXX`
   *replaces* PyPI entirely, and the pytorch wheel index hosts **no whisperx**. A single
   `pip install -e ".[asr]" --index-url <pytorch>` dies with
   *"No matching distribution found for whisperx"*. Correct shape: **step 1** install
   `torch torchaudio --index-url <pytorch>` (CUDA build), **step 2** install
   `deciwaves[asr]` from PyPI with **no** `--index-url` (torch already satisfied). CPU-only
   result → single step (CPU torch resolves from PyPI as an ordinary dep).

2. **PowerShell call operator.** Win11's default shell parses a line that *starts* with a
   quoted string as a string literal → `ParserError: Unexpected token '-m'`. Every command
   must be prefixed with `& ` so `& "C:\...python.exe" -m pip ...` runs. (Repo is
   Windows/PowerShell-only.)

3. **Absolute editable path.** `-e ".[asr]"` only resolves from the repo root; the user
   pastes into a fresh console at their home dir. Emit `-e "<abs-project-dir>[asr]"` via
   `_editable_project_dir()` (walks up for `pyproject.toml`).

The hint also carries an **"I've installed it — re-check"** button
(`AsrInstallHint.recheck_requested` → `GamePanel.asr_recheck_requested` →
`shell` → `DoctorPanel.recheck()`); a finished doctor run re-grades GPU/ASR readiness and
hides the hint, so no app restart is needed after installing.

Actual pip execution from the GUI is still deferred to #77 — this is copy-paste only.
