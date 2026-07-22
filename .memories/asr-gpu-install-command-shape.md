---
description: The GUI's ASR/GPU install command — one --extra-index-url line, cu128, and the four footguns behind that shape
type: gui
---

# ASR / GPU install command: the shape and why

`src/deciwaves/gui/gpu_probe.py::build_asr_install_steps` builds the copy-pasteable
install command shown in `AsrInstallHint`. Dogfooding (2026-07-22) proved the naive
command fails for a real first-time user in several independent ways. The **validated**
final shape (end-to-end on an RTX 4080, driver 610.62 / CUDA UMD 13.3) is a **single
command**:

```
& "<venv>\python.exe" -m pip install -e "<abs-repo>[asr]" --extra-index-url https://download.pytorch.org/whl/cu128
```

Result: `torch 2.8.0+cu128`, `torch.cuda.is_available() == True`, `pip check` clean.

## The four footguns (each cost real debugging)

1. **`--extra-index-url`, NEVER `--index-url`.** `--index-url` *replaces* PyPI, and the
   pytorch wheel index hosts no `whisperx` → *"No matching distribution found for
   whisperx"*. `--extra-index-url` *adds* the index: whisperx resolves from PyPI, torch
   from the CUDA index. pip prefers the CUDA wheel because a `+cu128` local version sorts
   above the plain PyPI `2.8.0`, and resolving the whole graph honours whisperx's
   `torch~=2.8` pin (so versions stay consistent — no drift).
2. **The index must carry torch's pinned version.** `whisperx` (the only `[asr]` dep,
   `whisperx>=3.1,<4` → 3.8.6) pins `torch~=2.8`. **cu124 tops out at torch 2.6**, so a
   cu124 install gets silently replaced by CPU torch 2.8 to satisfy whisperx. torch 2.8
   CUDA wheels live on **cu126/cu128** → `_DEFAULT_WHEEL_TAG = "cu128"`, thresholds extend
   to cu128/cu126.
3. **nvidia-smi format.** Newer drivers print `"CUDA UMD Version: 13.3"`, not
   `"CUDA Version: 12.4"`; the parser regex must accept an optional word between
   `CUDA` and `Version:` or it falls back to the default tag.
4. **PowerShell call operator.** Win11's default shell ParserErrors on a line starting
   with a quoted path → prefix every command with `& `. Also emit an **absolute** repo
   path for `-e` (a fresh console opens at the home dir, not the repo).

## Approaches that were tried and rejected
- Single `--index-url` command → footgun #1.
- Two steps (torch-index first, then extra) → the extra's resolve pulls a **CPU torch
  back over** the CUDA one (last-writer-wins).
- Two steps reversed + `pip install torch --index-url` → pip sees `2.8.0` already
  satisfied and skips (treats `+cpu`/`+cu128` as the same version); adding
  `--force-reinstall --no-deps` works but grabs the index's *newest* torch (e.g. 2.11),
  **drifting off** whisperx's pin. Letting pip resolve the graph (`--extra-index-url`) is
  strictly better.

## Re-check after install
The hint carries an **"I've installed it — re-check"** button
(`AsrInstallHint.recheck_requested` → `GamePanel.asr_recheck_requested` → `shell` →
`DoctorPanel.recheck()`); a finished doctor run re-grades GPU/ASR readiness and hides the
hint — no app restart. Actual pip execution from the GUI is still deferred to #77.
