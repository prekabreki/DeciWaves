---
description: The HZD/FW "package" paths are subdirectories of the install, not the install root - LocalCacheDX12\package (HZDR) and LocalCacheWinGame\package (HFW)
type: reference
---

Verified against fresh installs (2026-07-15, E2E run):

- **HZD Remastered**: the package dir the pipeline needs (the one containing
  `PackFileLocators.bin`) is `<install>\LocalCacheDX12\package`, NOT the install root.
- **Forbidden West CE**: the dir containing `streaming_graph.core` is
  `<install>\LocalCacheWinGame\package`.
- **DS:DC** takes the install root itself (`data\*.bin` + `oo2core_7_win64.dll` live there).

`deciwaves setup` accepts any existing dir for `--hzd-package`, and doctor's HZD check
currently green-lights the install root, so a wrong path surfaces only as a
`FileNotFoundError` traceback at catalog time - issue #34 tracks mirroring the FW-style
validation (which names the expected subdir in its fix hint).
