# Bring-your-own inputs

DeciWaves ships code, never game content. A few inputs are genuinely game data - copyrighted
prose, or a type map generated from your own install - so DeciWaves cannot bundle them and
will not fetch them for you. This page documents each one: what it is, the exact format the
parser expects, where to put it, and the command flag that consumes it. You supply these from
your own legally owned copy, and DeciWaves reads them read-only like everything else.

Three inputs, in rough order of how likely you are to need them:

| Input | Game | Required? | Unlocks |
|-------|------|-----------|---------|
| `types.json` | FW | Required for subtitle-bind | Reading FW dialogue groups at all |
| Gamescript | FW | Optional | Speaker labels and true story order |
| Narrative transcript | DS | Optional | Sharper cutscene story order |

## Forbidden West: types.json (required)

subtitle-bind cannot read a single FW dialogue group without this file, so it is required for
the FW pipeline.

**What it is.** FW stores its objects in a binary format whose field layout is described by
the engine's RTTI (run-time type information) type database. `types.json` is that database
dumped to JSON. DeciWaves' loader (`deciwaves.engine.pack.fw_rtti.TypeRegistry`) reads it with
a plain `json.load` and expects a top-level object keyed by type name. The keys and shape the
loader actually reads:

    {
      "<TypeName>": {
        "kind": "compound",
        "bases": [ { "type": "<BaseTypeName>", "offset": 0 } ],
        "attrs": [ { "name": "<AttrName>", "type": "<AttrType>", "offset": 0, "flags": 0 } ]
      }
    }

For each type the loader uses `kind`, the `bases` list (each entry a `type` name and an integer
`offset`; a base with a negative offset is an extension type and is skipped), and the `attrs`
list (each entry a `name`, a `type`, an integer `offset`, and optional `flags`). The `offset`
values are the real C++ member offsets from the dump: DeciWaves computes each compound's
on-disk field order by flattening base classes first, sorting attributes by offset, then
dropping any whose `flags` set the do-not-serialize-binary bit (value 2). It hashes every type
name to its on-disk type id with a version-prefixed MurmurHash3. An `attrs` entry with no
`name` is treated as a category marker and ignored. If your file's shape differs from this,
deserialization won't line up.

**Where it comes from.** This is the format emitted by odradek, an open Decima RTTI tool, when
pointed at a Forbidden West build. DeciWaves doesn't ship it, doesn't download it, and doesn't
point you at a copy to grab - generate it yourself from the install you own. The type map is a
machine schema rather than dialogue, but it is still derived from the game and is yours to
produce.

**Where to put it.** subtitle-bind looks for `types.json` in the workspace root by default.
Put it there, or point at it explicitly:

    deciwaves --workspace D:\deciwaves fw subtitle-bind --package-dir <pkg> --types-json D:\path\to\types.json

`deciwaves fw run` uses the default workspace-root location. If the file is missing,
subtitle-bind stops with a message naming the path it looked for and pointing back to this
page.

## Forbidden West: gamescript (optional)

subtitle-bind gives every clip its exact on-screen subtitle, but not who said it or where it
falls in the story. A gamescript supplies both. It is optional: without it, `fw run` stops
cleanly after subtitle-bind with subtitle-labeled reels; with it, the pipeline continues into
match -> full-reel -> render and produces speaker-attributed, story-ordered reels.

**What it is.** A play-order transcript of the game's dialogue as plain text. The parser
(`deciwaves.games.fw.gamescript.parse`) walks it line by line and expects:

- One spoken line per line, written `Speaker: text`. The speaker starts with a capital letter,
  holds no colon, and runs up to about 40 characters; the first `: ` splits speaker from text.
  Examples: `Aloy: ...`, `Tilda van der Meer: ...`, `Aloy & Morlund: ...`.
- Lines that start with `[` (stage directions like `[Aloy climbs the cliff]`) are skipped.
  Parentheticals inside a spoken line, such as `(sighs)` or `(offscreen)`, are stripped from
  the text.
- Quest and section headers on their own line. An ALL-CAPS line (`THE EMBASSY`) is read as a
  main-quest header; a short Title-Case line with no sentence-ending punctuation and at most
  seven words (`Breaking Even`) is read as a sidequest header. Every following spoken line
  inherits the most recent header as its quest until the next header appears.
- Preamble text above the first spoken line (page metadata and the like) is ignored:
  Title-Case headers only start counting once real dialogue has begun.

Each spoken line becomes an ordered record of (index, speaker, text, quest). That order is the
story spine: the match stage aligns each clip's exact subtitle to a script line, and the
matched line supplies the speaker, the quest, and the near-chronological position at once.

**Where to put it.** `deciwaves fw run` takes the path explicitly with `--gamescript`:

    deciwaves --workspace D:\deciwaves fw run --gamescript D:\path\to\gamescript.md

Or persist it once so you never have to pass the flag again -- including from guided mode
(bare `deciwaves`), which otherwise has no way to reach match/full-reel/render:

    deciwaves setup --fw-gamescript D:\path\to\gamescript.md

An explicit `--gamescript` on a given `fw run` still beats a configured `fw_gamescript`, so
you can override it for one run without losing the saved default. `deciwaves doctor` reports
`fw_gamescript` alongside the other configured paths; if it was configured and the file has
since moved, `fw run`/`doctor` treat that the same as any other configured-but-missing path --
loudly, with a nonzero exit -- rather than silently falling back to "no gamescript at all".

The standalone match stage (`deciwaves fw match`) instead defaults to
`docs/forbidden_west_gamescript.md` under the workspace, or takes its own `--gamescript`.

This is copyrighted game dialogue. DeciWaves does not ship it and never will; supply your own
from the game you own.

## Death Stranding: narrative transcript (optional)

DS story order is good without any extra input - cutscenes fall into a sensible numeric order
by default. A narrative transcript makes it sharper by anchoring each cutscene to its real
position in the story.

**What it is.** An in-order transcript of the narrative as plain text, matching what the anchor
parser (`deciwaves.engine.transcript_anchor.build_index`) reads:

- One line per spoken line. A `Speaker: text` line is accepted and the speaker prefix is
  stripped; a bare line with no `Speaker:` prefix is taken as the text itself.
- A line that is entirely a bracketed marker (`[Chapter 2]`) is treated as a scene break and
  skipped.
- Only lines whose normalized text is at least 20 characters are indexed, and each distinct
  line is indexed once in first-seen order. Normalization lowercases the text, folds smart
  quotes, and strips punctuation, so near-verbatim subtitles still match.

The result is a lookup from normalized line to its position in the narrative. Story order then
anchors a cutscene scene to the median position of whichever of its subtitles it finds in that
index. Against the DS script this matches around 93% of distinctive cutscene subtitles, which
is enough to pin scenes accurately.

**Where to put it, and one honest limitation.** The transcript is consumed only by the order
stage, through its `--transcript` flag:

    deciwaves --workspace D:\deciwaves ds order --transcript D:\path\to\transcript.txt

`deciwaves ds run` does not expose a `--transcript` flag, so the all-in-one run always uses the
default numeric cutscene order. Anchoring with a transcript means running the order stage
yourself with the flag set (and pointing its other inputs, the catalog and the cutscene track
list, at the files you want - see `deciwaves ds order --help`), then re-rendering. Passing an
empty path, or none, disables anchoring and falls back to numeric order; a path you *do* pass
that doesn't exist is treated as a mistake - the order stage errors and exits nonzero naming
the path, rather than silently falling back.

This is copyrighted game prose. DeciWaves does not ship it and never will; supply your own from
the game you own.

## Horizon Zero Dawn: narrative transcript (optional, internal-only)

HZD has the same category of input as the DS transcript above - a narrative transcript that
could anchor cutscene/quest order to the real story - but it is not wired up to anything you can
pass in yet. Unlike DS, no HZD stage exposes a `--transcript` flag (transcripts are per-game BYO
inputs consumed only through such stage flags, disabled by default), so the pipeline always falls
back to episode/scene order (see `deciwaves.games.hzd.render`). There is nothing to configure here
today; this section exists so the intent is on record for whoever wires up HZD transcript
anchoring later.
