---
description: DS2's 7 non-RIFF slot-0 locators are a 2-byte skew (identical `f1 10` prefix, valid Wwise header at offset+2), not corruption -- but reading from +2 still fails to decode because the chunk after `fmt ` is misaligned by 2 bytes
type: reference
---

Measured 2026-08-01 against the retail DS2 install, while reviewing PR #365 (issue #360).
Detail behind the one-line mention in [[ds2-audio-binding]].

## What the 7 are

Of DS2's 8,776 slot-0 dialogue locators, exactly 7 do not start with `RIFF`, so
`FwStreamStore.read_riff_clip` raises `ValueError` and `deciwaves ds2 extract` counts them as
per-line failures (`ok == 8769, failed == 7` on a full retail run — reproduced exactly).

| line_id | file_index | offset |
| --- | --- | --- |
| `g495_0087` | 40 | 141,988,345 |
| `g483_0020` | 39 | 116,945,984 |
| `g1441_0012` | 39 | 135,705,080 |
| `g815_0100` | 39 | 146,512,470 |
| `g1372_0031` | 39 | 229,474,561 |
| `g11396_0010` | 38 | 33,516,875 |
| `g6888_0001` | 38 | 33,996,916 |

## They are not corruption

All 7 share an **identical 2-byte prefix `f1 10`**, with a well-formed Wwise header beginning at
`offset + 2`:

    f1 10 | 52 49 46 46 <size> 57 41 56 45 66 6d 74 20 | 42 00 00 00 | ff ff | 01 00 | 80 bb 00 00
           R  I  F  F           W  A  V  E  f  m  t         66          0xFFFF   mono    48000

That is the same `fmt` shape as the 8,769 good clips — so these are real dialogue lines, not
padding or garbage.

## But +2 does not recover them

Reading `read(fi, offset + 2, riff_size + 8)` yields a clip whose `fmt ` chunk parses correctly
(size 66, at byte 12) — and whose **next chunk is misaligned by exactly 2 bytes**: `hash` appears
at byte 84 where the `fmt ` size implies 86. A good clip reads `fmt `@12 → `hash`@86 → `data`@110;
the skewed one reads `fmt `@12 → `sh\x10\x00`@86 and stops. `vgmstream-cli` rejects all 7 with
`no 'data' tag found` (verified: rc=1, 0-byte output, on every one).

So the skew is not a constant shift that a `+2` read repairs — something is inserted or removed
*inside* the clip, not merely in front of it. Recovering them means understanding that, which was
judged not worth it at 7 / 8,776 = **0.08%** of DS2 dialogue.

The **correct handling is to tolerate them**, which is what `games/ds2/extract.py` does (per-line
`ValueError` → `extract-errors.log`, never written to the resume sidecar, run does not abort).
Do not "fix" this by reading from `offset + 2` — that produces a clip that still will not decode.
