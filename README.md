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
| Horizon Zero Dawn | Remastered (PC) | Yes | Audio is tied to lines by content fingerprint; ambiguous fingerprint collisions are confirmed with on-device transcription, capped by default at 300 buckets rather than a full-library pass (`--sample-cap 0` for uncapped). Reels come out in episode order. |
| Horizon Forbidden West | Complete Edition (PC) | Yes | Clips carry their exact in-game subtitle. Speaker labels and true story order need two bring-your-own inputs (a `types.json` and a gamescript); without them you still get subtitle-labeled reels. See [docs/BYO.md](docs/BYO.md). |

## Install

    pip install deciwaves

HZD and FW also need the GPU transcription extra (WhisperX). Install it together with a
PyTorch build that matches your CUDA version (see https://pytorch.org/get-started/locally/):

    pip install deciwaves[asr]

Or install from a clone -- for development, or to run the latest unreleased code:

    git clone https://github.com/prekabreki/DeciWaves
    cd DeciWaves
    pip install .

Then fetch the decode tools, point DeciWaves at your game, and check the result:

    deciwaves setup --ds-install "C:\...\DEATH STRANDING DIRECTORS CUT"
    deciwaves doctor

`setup` downloads vgmstream-cli, VGAudioCli, and ffmpeg into `%LOCALAPPDATA%\DeciWaves\tools`
(skipping any tool already present there -- pass `--force` to refetch anyway), finds the
Oodle DLL next to a DS install, and writes `config.json`. Pass `--hzd-package` or
`--fw-package` for those games instead, and (optionally) `--fw-gamescript` to persist your own
FW gamescript transcript so `fw run` and guided mode don't need `--gamescript` passed by hand
every time. It exits nonzero if any tool failed to download. `doctor` prints a preflight report
and returns success as long as every required tool is present; a game you don't own shows
`[--] not configured` and never fails the check.

## Quick start - pick your game

The fastest path is guided mode. Run `deciwaves` with no arguments:

    deciwaves

It detects which games you have configured, asks which one to extract, confirms a workspace
directory (and, for FW, optionally asks for your gamescript path if one isn't already
configured - see below - so guided mode can reach match/full-reel/render too, not just
subtitle-bind), and runs that game's full pipeline. This is the same pipeline the explicit commands
run; it only adds the menu around it. In a non-interactive shell it prints usage and exits
instead of blocking.

If you'd rather drive it yourself, each game has an explicit `run` command. The global
`--workspace` flag sets where output lands (default: the current directory) -- it must come
*before* the game name (`deciwaves --workspace DIR ds run`, not `deciwaves ds --workspace DIR
run`, which is parsed as that stage's own argument instead). A relative path you pass to a
stage's own flag (e.g. `--gamescript`) that already exists is resolved against the directory
you ran `deciwaves` from, not against `--workspace` -- it doesn't need to sit inside the
workspace. A relative path that doesn't exist yet (e.g. a stage's own output path) is left
alone and stays workspace-relative, same as always. A path saved earlier via `deciwaves setup`
is always absolute regardless.

### Death Stranding (no GPU)

    deciwaves --workspace D:\deciwaves ds run

This chains catalog -> order -> render. The catalog stage parses your install into
`out/catalog.csv` (roughly 27,000 rows, one per voice line); order builds `out/playlist.csv`;
render encodes the MP3 reels and their tracklists into `out/audio`. The catalog parse and the
render are the slow parts, each in the range of tens of minutes on a mid-range machine and
longer on a slow disk. No GPU is involved anywhere in the default DS chain.

### Horizon Zero Dawn Remastered

    pip install deciwaves[asr]
    deciwaves --workspace D:\deciwaves hzd run

HZD chains catalog -> clip-index -> wem-metadata -> bind -> render. Structural binding
(content fingerprinting) resolves the vast majority of rows before any ASR runs at all; the
bind stage needs the `[asr]` extra and a CUDA GPU only to run WhisperX over what's left --
ambiguous fingerprint collisions. By default that ASR pass is capped at 300 ambiguous buckets
rather than running for hours over the full library; pass `--sample-cap 0` to `hzd run` (or
`hzd bind`) for an uncapped full pass instead, or any other number for a custom cap. On one
real install the capped default still bound 54,564 of 54,566 rows (99.996%), because
structural binding had already covered almost everything -- the cap costs little in practice,
and whenever it does leave buckets untranscribed, bind's own output states exactly how many.
Those numbers also land on disk: `wem-metadata` and `bind` each merge a summary section
(story-line coverage; cap used, buckets skipped, tier tally) into `out/hzd/coverage.json`,
so a capped rip is distinguishable from a complete one without re-reading the run's stdout.
Note: if `bind` already completed in a workspace, changing `--sample-cap` on a later `hzd run`
has no effect until you delete `out/hzd/.done-bind` and re-run it -- the done-marker doesn't
know its own flags changed. bind also checkpoints as it goes (see Resume, below), so an
interrupted bind picks up where it stopped.

### Horizon Forbidden West

    deciwaves --workspace D:\deciwaves fw run

FW chains extract -> asr -> subtitle-bind, which gets you clips labeled with their exact
in-game subtitle. The asr stage needs the `[asr]` extra and a GPU. subtitle-bind requires a
`types.json` (a Decima type map for FW) in the workspace root. Speaker labels and real story
order additionally need your own copy of the FW gamescript, passed with `--gamescript` (or set
once with `deciwaves setup --fw-gamescript <path>`, so you never have to pass the flag again).
Both are bring-your-own inputs that this repo does not and will not ship - see
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

The decode-heavy stages (`ds render`, `hzd clip-index`, `hzd render`, `fw extract`) decode
clips concurrently and take a `--jobs N` flag (default `min(8, cpu_count)`); this is the
single biggest speed-up on a multi-core machine. `--jobs 1` forces the old one-at-a-time
decode. `deciwaves <game> run` uses the default automatically.

### Death Stranding (`deciwaves ds ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| catalog | Build the line catalog from your install | `--data-dir`, `--oodle` |
| order | Build the story-ordered playlist | `--transcript` (BYO, see [docs/BYO.md](docs/BYO.md)) |
| render | Render MP3 reels + tracklists | `--main-story`, `--speech-trim`, `--bitrate`, `--jobs` |
| cutscenes | Resolve cutscene voice tracks | standalone; `run` uses a bundled track list |
| trim | [GPU] Rebuild the speech-trim manifest | standalone |

`ds run` chains catalog -> order -> render. cutscenes and trim are not in that chain: `run`
ships pre-resolved data for them and leaves them available to regenerate against your own
install by hand.

### Horizon Zero Dawn (`deciwaves hzd ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| catalog | Build the line catalog | `--package` |
| clip-index | Fingerprint audio clips | `--package`, `--jobs` |
| wem-metadata | Extract wem metadata + coverage | `--package` |
| bind | [GPU] Bind clips to lines | `--package`, `--transcripts`, `--transcripts-out`, `--sample-cap` (default 300, 0 = unlimited) |
| render | Render MP3 reels + tracklists | `--out-dir`, `--jobs` |

### Horizon Forbidden West (`deciwaves fw ...`)

| Stage | What it does | Key flags |
|-------|--------------|-----------|
| extract | Extract dialogue clips to WAV | `--package`, `--jobs` |
| asr | [GPU] Transcribe clips | `--roster`, `--model`, `--limit` |
| subtitle-bind | Label clips with exact subtitles | `--package-dir`, `--types-json` (BYO) |
| match | Speaker + story order (needs BYO gamescript) | `--gamescript` (BYO) |
| full-reel | Assemble the full-reel manifest | |
| weave | Woven story manifest | |
| dlc | Burning Shores manifest | |
| assemble | Concatenate manifests | |
| render | Render MP3 reels + tracklists | `--manifest`, `--tiers` |

`fw run` chains extract -> asr -> subtitle-bind, then continues match -> full-reel -> render
once a `--gamescript` is supplied (explicitly, or via a `--fw-gamescript` configured earlier
with `deciwaves setup`).

## Configuration

`deciwaves setup` writes `config.json` to `%LOCALAPPDATA%\DeciWaves\config.json`. It records
the tools directory, the install path for each game you configured (`ds_install`,
`hzd_package`, `fw_package`, `oodle_dll`), and your optional FW gamescript path
(`fw_gamescript`, set with `--fw-gamescript`). Set `DECIWAVES_CONFIG_DIR` to keep that file
somewhere else.

Each run merges its flags over what's already saved -- an omitted flag keeps its previous
value, so running `deciwaves setup --hzd-package ...` later doesn't blank out a `--ds-install`
configured earlier. Pass a flag again (with a new path) to update it. To *clear* a saved path
(e.g. a stale `ds_install` or `fw_gamescript` that now points nowhere and makes `doctor` fail),
pass it as an explicit empty string: `deciwaves setup --ds-install ""` unsets it (omitting the
flag keeps it; only an explicit `""` clears).

Environment overrides, all optional:

- `DECIWAVES_CONFIG_DIR` - directory that holds `config.json` (default `%LOCALAPPDATA%\DeciWaves`).
- `DECIWAVES_VGMSTREAM` - full path to `vgmstream-cli.exe`, overriding the configured tools dir and PATH.
- `DECIWAVES_VGAUDIO` - full path to `VGAudioCli.exe`, same idea.

Workspace layout. `--workspace` (default: the current directory) is the root everything is
written under, all inside `out/`. DS writes `out/catalog.csv`, `out/playlist.csv`, and reels
in `out/audio`; HZD and FW write under `out/hzd/` and `out/fw/`.

Resume. `deciwaves <game> run` writes a marker file at `out/<game>/.done-<stage>` after each
stage finishes cleanly, and skips any stage whose marker already exists. To force a stage to
re-run, delete its marker and run again; the stages before it stay skipped, but re-running
that stage also deletes every LATER stage's marker in the chain, so downstream stages re-run
too instead of resuming from what's now stale data. A stage's output existing is deliberately
not treated as done - only its marker is - so a crash mid-stage never looks finished. The HZD
bind stage also checkpoints within itself: its `--transcripts-out` sidecar lets a restarted
bind reuse the clips it already transcribed. A marker also doesn't know if the flags used to
produce it have since changed - re-running `hzd run` with a different `--sample-cap` after
`bind` already has a marker is a no-op until you delete `out/hzd/.done-bind` yourself.

Partial runs. `run --until <stage>` stops the chain after that stage (markers skip and
invalidate as usual), and the GPU-extra check only applies to stages actually in the slice -
so `hzd run --until wem-metadata` or `fw run --until extract` runs the cheap pre-GPU stages
on a machine without `deciwaves[asr]`. `run --from <stage>` is the delete-the-marker flow
above as a flag: it removes that stage's marker and runs, so it and everything after it
re-execute while earlier stages stay skipped. `run --help` for each game lists its stage
names.

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
