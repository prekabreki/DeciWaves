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

Fixed in issue #34: doctor's `check_hzd_package` (src/deciwaves/cli/doctor.py) now requires
`PackFileLocators.bin` to exist under the given path, mirroring `check_fw_package`'s
`streaming_graph.core` check. `games/hzd/profile.py`'s `hzd_package_error()` gives the same
validation an actionable, non-traceback failure at `hzd catalog`'s entry point (mirrors
`games.fw.subtitle_bind.types_json_error`). `deciwaves setup --hzd-package` now prints a
non-blocking WARNING when the path is wrong, and suggests the exact `LocalCacheDX12\package`
subdir when it detects the user pointed at the install root.
