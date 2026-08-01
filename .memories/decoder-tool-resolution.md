---
description: Decoder tool paths are set at RUNTIME by config.apply_tool_env, so a shell check for DECIWAVES_VGMSTREAM or a PATH lookup reports "no decoder installed" on a fully configured machine -- ask `deciwaves doctor`, never the shell
type: reference
---

Two independent traps make a correctly-configured DeciWaves install look broken. Both cost
real time on 2026-08-01 (concluded, wrongly, that no Wwise decoder existed on the dev box).

## 1. The tool env vars are runtime-set, not persisted

`cli.config.apply_tool_env` prepends the configured `tools_dir` to `PATH` and
`os.environ.setdefault`s each tool's override var (`DECIWAVES_VGMSTREAM`,
`DECIWAVES_VGAUDIO`) **at CLI/GUI startup**, from `tools_dir` in `config.json`. Nothing is
written to the User or Machine environment.

Consequences:

- `echo $DECIWAVES_VGMSTREAM` / `[Environment]::GetEnvironmentVariable(...)` return empty on a
  machine where every tool resolves fine.
- `command -v vgmstream-cli` fails too, because the exe lives in `tools_dir` (which may be a
  UNC path such as a NAS share), not on the persisted `PATH`.
- `doctor` reports the source it matched — `(env ...)`, `(tools_dir)`, or `(PATH)` — so
  `(env DECIWAVES_VGMSTREAM)` on a machine whose shell has no such var is **not** a
  contradiction; it is `apply_tool_env` having just set it.

**How to apply:** `deciwaves doctor` (or `doctor --json`) is the only authority on whether a
tool resolves. A shell probe is a false negative. Registered tools live in `cli.config.TOOLS`
with pinned download URLs; `deciwaves setup` fetches and unpacks them into `tools_dir` with a
per-tool file manifest, so "install the decoder" is already a solved, one-command job — never
add a new download path or vendor a binary for it.

## 2. The `.venv` interpreter virtualizes `%LOCALAPPDATA%`

`config.path()` prints `C:\Users\<u>\AppData\Local\DeciWaves\config.json` while Git Bash `ls`
and PowerShell `Test-Path` both report that exact path missing — the venv inherits Store
Python's MSIX redirection, so the real file sits in the package shadow under
`AppData\Local\Packages\PythonSoftwareFoundation...\LocalCache\Local\`. See the global memory
`store-python-child-process-dll-trap` for the full mechanism and its nastier DLL variant.

**How to apply:** verify config through the code (`deciwaves.cli.config.load()`), not through
a shell stat of the printed path.

## Which decoder per game

- DS1, HZD **and DS2** are Wwise `.wem` -> `vgmstream-cli` (see [[ds-wwise-wem-format]],
  [[ds2-audio-binding]]).
- FW is RIFF/ATRAC9 -> `VGAudioCli`.

DS2 therefore needs no new tooling at all; it reuses the existing `vgmstream-cli` entry.
