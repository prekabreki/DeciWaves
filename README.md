# DeciWaves

Turn the voice acting in a Decima-engine game you own into an audiobook of its own story.

You bought Death Stranding, Horizon Zero Dawn, or Horizon Forbidden West. Somewhere in
that install are thousands of recorded lines: main-story cutscenes, side conversations,
codec calls, ambient barks. They are locked inside the game's proprietary archives and
playable only in the order the game decides. DeciWaves reads your install, read-only, and
pulls those lines out with the speaker and the on-screen subtitle attached wherever it can
derive them.

It then puts the lines back in story order and encodes them into MP3 reels you can drop on a
phone and listen to like an audiobook. Nothing is fetched from the game's servers and nothing
in your install is modified. DeciWaves ships code only, and every second of audio it produces
comes off your own disk.

> **Requirements up front:** Windows 10/11 - Python 3.12+ - a legally owned PC install of the
> game you're extracting - about 10 GB free disk - (HZD and FW only) an NVIDIA GPU for the
> transcription stages. Death Stranding needs no GPU.

**Not affiliated with Guerrilla Games, Kojima Productions, or Sony Interactive
Entertainment.** DeciWaves ships code only - no game files, no dialogue text. It never
modifies your install (read-only), and its output is for your personal use.

## Supported games

| Game | Edition | GPU needed | What you get |
|------|---------|------------|--------------|
| Death Stranding | Director's Cut (PC) | No | Lines identified straight from the Decima resource tree, with speaker and subtitle. Cutscene audio is whole-scene, not per-line. Story order is solid by default and sharper with an optional bring-your-own transcript. |
| Horizon Zero Dawn | Remastered (PC) | Yes | Audio is tied to lines by content fingerprint and confirmed with on-device transcription, so the bind stage runs for hours on a full library. Reels come out in episode order. |
| Horizon Forbidden West | Complete Edition (PC) | Yes | Clips carry their exact in-game subtitle. Speaker labels and true story order need two bring-your-own inputs (a `types.json` and a gamescript); without them you still get subtitle-labeled reels. See [docs/BYO.md](docs/BYO.md). |

## Install

DeciWaves is not on PyPI yet, so install it from a clone:

    git clone https://github.com/prekabreki/DeciWaves
    cd DeciWaves
    pip install .

HZD and FW also need the GPU transcription extra (WhisperX). Install it together with a
PyTorch build that matches your CUDA version (see https://pytorch.org/get-started/locally/):

    pip install ".[asr]"

Then fetch the decode tools, point DeciWaves at your game, and check the result:

    deciwaves setup --ds-install "C:\...\DEATH STRANDING DIRECTORS CUT"
    deciwaves doctor

`setup` downloads vgmstream-cli, VGAudioCli, and ffmpeg into `%LOCALAPPDATA%\DeciWaves\tools`,
finds the Oodle DLL next to a DS install, and writes `config.json`. Pass `--hzd-package` or
`--fw-package` for those games instead. It exits nonzero if any tool failed to download.
`doctor` prints a preflight report and returns success as long as every required tool is
present; a game you don't own shows `[--] not configured` and never fails the check.

## Quick start - pick your game

The fastest path is guided mode. Run `deciwaves` with no arguments:

    deciwaves

It detects which games you have configured, asks which one to extract, confirms a workspace
directory, and runs that game's full pipeline. This is the same pipeline the explicit commands
run; it only adds the menu around it. In a non-interactive shell it prints usage and exits
instead of blocking.

If you'd rather drive it yourself, each game has an explicit `run` command. The global
`--workspace` flag sets where output lands (default: the current directory).

### Death Stranding (no GPU)

    deciwaves --workspace D:\deciwaves ds run

This chains catalog -> order -> render. The catalog stage parses your install into
`out/catalog.csv` (roughly 27,000 rows, one per voice line); order builds `out/playlist.csv`;
render encodes the MP3 reels and their tracklists into `out/audio`. The catalog parse and the
render are the slow parts, each in the range of tens of minutes on a mid-range machine and
longer on a slow disk. No GPU is involved anywhere in the default DS chain.

### Horizon Zero Dawn Remastered

    pip install ".[asr]"
    deciwaves --workspace D:\deciwaves hzd run

HZD chains catalog -> clip-index -> wem-metadata -> bind -> render. The bind stage runs
WhisperX transcription to confirm the fingerprint match, so it needs the `[asr]` extra and a
CUDA GPU, and it runs for hours on a full library. It checkpoints as it goes (see Resume,
below), so an interrupted bind picks up where it stopped.

### Horizon Forbidden West

    deciwaves --workspace D:\deciwaves fw run

FW chains extract -> asr -> subtitle-bind, which gets you clips labeled with their exact
in-game subtitle. The asr stage needs the `[asr]` extra and a GPU. subtitle-bind requires a
`types.json` (a Decima type map for FW) in the workspace root. Speaker labels and real story
order additionally need your own copy of the FW gamescript, passed with `--gamescript`. Both
are bring-your-own inputs that this repo does not and will not ship - see
[docs/BYO.md](docs/BYO.md). Without a gamescript, `fw run` stops cleanly after subtitle-bind
and tells you what it's waiting for.

## How it works

DeciWaves reads the Decima archives in your install and never writes to them. Each game needs
its own way of tying an audio clip to the line it voices: DS parses the Decima resource tree
with a bundled, patched pydecima; HZD fingerprints each clip and confirms the match with
on-device transcription; FW replays its streaming-graph index and reads the exact subtitle out
of each dialogue group. The encoded payload is Wwise `.wem` (DS) or ATRAC9 (HZD and FW),
decoded to WAV by vgmstream-cli or VGAudioCli. A per-game story-order pass arranges the lines,
and ffmpeg encodes them into MP3 reels capped near 290 MB, each with a plain-text tracklist.
For the full design - package layout, the per-game solutions, the pipeline seam - see
[docs/architecture.md](docs/architecture.md).

## Stage-by-stage usage

`deciwaves <game> run` is the whole pipeline. You can also run any single stage as
`deciwaves <game> <stage> [flags]`, and `deciwaves <game> <stage> --help` prints that stage's
own flags. `[GPU]` marks stages that need the `[asr]` extra and a CUDA GPU.

### Death Stranding (`deciwaves ds ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| catalog | Build the line catalog from your install | `--data-dir`, `--oodle` |
| order | Build the story-ordered playlist | `--transcript` (BYO, see [docs/BYO.md](docs/BYO.md)) |
| render | Render MP3 reels + tracklists | `--main-story`, `--speech-trim`, `--bitrate` |
| cutscenes | Resolve cutscene voice tracks | standalone; `run` uses a bundled track list |
| trim | [GPU] Rebuild the speech-trim manifest | standalone |

`ds run` chains catalog -> order -> render. cutscenes and trim are not in that chain: `run`
ships pre-resolved data for them and leaves them available to regenerate against your own
install by hand.

### Horizon Zero Dawn (`deciwaves hzd ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| catalog | Build the line catalog | `--package` |
| clip-index | Fingerprint audio clips | `--package` |
| wem-metadata | Extract wem metadata + coverage | `--package` |
| bind | [GPU] Bind clips to lines | `--package`, `--transcripts`, `--transcripts-out` |
| render | Render MP3 reels + tracklists | `--out-dir` |

### Horizon Forbidden West (`deciwaves fw ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| extract | Extract dialogue clips to WAV | `--package` |
| asr | [GPU] Transcribe clips | `--roster`, `--model`, `--limit` |
| subtitle-bind | Label clips with exact subtitles | `--package-dir`, `--types-json` (BYO) |
| match | Speaker + story order (needs BYO gamescript) | `--gamescript` (BYO) |
| full-reel | Assemble the full-reel manifest | |
| weave | Woven story manifest | |
| dlc | Burning Shores manifest | |
| assemble | Concatenate manifests | |
| render | Render MP3 reels + tracklists | `--manifest`, `--tiers` |

`fw run` chains extract -> asr -> subtitle-bind, then continues match -> full-reel -> render
once a `--gamescript` is supplied.

## Configuration

`deciwaves setup` writes `config.json` to `%LOCALAPPDATA%\DeciWaves\config.json`. It records
the tools directory and the install path for each game you configured (`ds_install`,
`hzd_package`, `fw_package`, `oodle_dll`). Set `DECIWAVES_CONFIG_DIR` to keep that file
somewhere else.

Each run merges its flags over what's already saved -- an omitted flag keeps its previous
value, so running `deciwaves setup --hzd-package ...` later doesn't blank out a `--ds-install`
configured earlier. Pass a flag again (with a new path) to update it.

Environment overrides, all optional:

- `DECIWAVES_CONFIG_DIR` - directory that holds `config.json` (default `%LOCALAPPDATA%\DeciWaves`).
- `DECIWAVES_VGMSTREAM` - full path to `vgmstream-cli.exe`, overriding the configured tools dir and PATH.
- `DECIWAVES_VGAUDIO` - full path to `VGAudioCli.exe`, same idea.

Workspace layout. `--workspace` (default: the current directory) is the root everything is
written under, all inside `out/`. DS writes `out/catalog.csv`, `out/playlist.csv`, and reels
in `out/audio`; HZD and FW write under `out/hzd/` and `out/fw/`.

Resume. `deciwaves <game> run` writes a marker file at `out/<game>/.done-<stage>` after each
stage finishes cleanly, and skips any stage whose marker already exists. To force one stage to
re-run, delete its marker and run again; the stages before it stay skipped. A stage's output
existing is deliberately not treated as done - only its marker is - so a crash mid-stage never
looks finished. The HZD bind stage also checkpoints within itself: its `--transcripts-out`
sidecar lets a restarted bind reuse the clips it already transcribed.

Bring-your-own inputs. The optional DS transcript, the required FW `types.json`, and the
optional FW gamescript are all documented in [docs/BYO.md](docs/BYO.md), including the exact
format each parser expects.

## Troubleshooting

Run `deciwaves doctor` first. It reports each decode tool, the Oodle DLL, every configured
install, the ASR extra, and CUDA, and names the fix for anything missing.

Common failures:

- **Tool not found.** `doctor` shows a tool as `[--] not found`. Re-run `deciwaves setup` to
  fetch it, put the executable on PATH, or point `DECIWAVES_VGMSTREAM` / `DECIWAVES_VGAUDIO`
  at it.
- **Wrong install directory.** A game shows an error like "has no data/ dir" or "no
  streaming_graph.core". Re-run `deciwaves setup --ds-install` / `--hzd-package` /
  `--fw-package` with the correct path; the doctor message names the exact file it expects to
  find.
- **No CUDA.** The `[asr]` extra is installed but `doctor` reports no GPU visible, so the GPU
  stages (`hzd bind`, `fw asr`) won't run. Install a PyTorch build matching your CUDA version
  (https://pytorch.org/get-started/locally/). DS needs none of this.
- **Windows Store Python.** The Microsoft Store build of Python virtualizes writes under
  `%LOCALAPPDATA%`, which can hide or misplace DeciWaves' `config.json` and tools. Install
  Python from python.org instead, or set `DECIWAVES_CONFIG_DIR` to a plain directory you
  control.
- **Windows Store Python, second-order variant.** Even when `config.json` resolves fine, a
  tools directory fetched under `%LOCALAPPDATA%` by `deciwaves setup` still lands inside that
  same virtualized shadow. The parent Python resolves the tool there without trouble, but the
  spawned `vgmstream-cli`/`ffmpeg` child process can't find its own side-by-side DLLs at the
  real path and dies with an exit code like `0xC0000135` (STATUS_DLL_NOT_FOUND) -- every clip
  fails and `render` reports zero decoded clips. The mitigation is the same, and matters more
  here: use a python.org Python, or pass a plain directory outside `%LOCALAPPDATA%` to both
  `DECIWAVES_CONFIG_DIR` and `deciwaves setup --tools-dir`.

## License

MIT (see [LICENSE](LICENSE)). The bundled pydecima is also MIT (see
[src/deciwaves/_vendor/pydecima/LICENSE](src/deciwaves/_vendor/pydecima/LICENSE)).
