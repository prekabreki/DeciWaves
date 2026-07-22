"""Qt-free issues-panel model (#69, spec §5.4).

Gathers what the pipeline records about dropped/failed lines: per-stage ``*-errors.log``
files (one ``<id>\\t<Type>: <msg>`` per line, harvest read-errors tagged ``harvest:<hash>``
inside catalog/wem-metadata logs) and DS's ``render-dupes.csv``. Log names are NOT uniform
(HZD bind writes ``asr-manifest-errors.log``; DS render/dupes live at the ``out/`` root), so
the paths are listed explicitly per game rather than derived from stage names."""
from __future__ import annotations

import os
from dataclasses import dataclass

# error logs to surface, relative to the workspace's out/ dir, per game.
_ERROR_LOGS = {
    "ds": ["catalog-errors.log", "cutscene-trim-errors.log", "render-errors.log"],
    "hzd": ["hzd/catalog-errors.log", "hzd/clip-index-errors.log",
            "hzd/wem-metadata-errors.log", "hzd/asr-manifest-errors.log",
            "hzd/render-errors.log"],
    "fw": ["fw/extract-errors.log", "fw/render-errors.log"],
}
# within-scene dupes the render stage drops (DS only), relative to out/.
_DUPES = {"ds": "render-dupes.csv"}

_SAMPLE_CAP = 20


@dataclass(frozen=True)
class IssueGroup:
    source: str        # basename shown in the panel, e.g. "catalog-errors.log"
    path: str          # absolute-ish path for the "open file" affordance
    count: int
    sample: list[str]  # first few lines, for an inline preview
    benign: bool = False  # housekeeping, NOT an error (e.g. render-dupes.csv): the panel
    # must present these separately so a successful run never reports them as "Issues".


def _read_error_lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


def _csv_data_rows(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            n = sum(1 for ln in f if ln.strip())
    except OSError:
        return 0
    return max(0, n - 1)  # exclude the header row


def gather_issues(workspace: str, game: str) -> list[IssueGroup]:
    out = os.path.join(workspace, "out")
    groups: list[IssueGroup] = []
    for rel in _ERROR_LOGS.get(game, []):
        path = os.path.join(out, rel)
        lines = _read_error_lines(path)
        if lines:
            groups.append(IssueGroup(source=os.path.basename(rel), path=path,
                                     count=len(lines), sample=lines[:_SAMPLE_CAP]))
    dupes = _DUPES.get(game)
    if dupes:
        path = os.path.join(out, dupes)
        n = _csv_data_rows(path)
        if n > 0:
            groups.append(IssueGroup(source=dupes, path=path, count=n, sample=[],
                                     benign=True))
    return groups


def split_issues(groups: list[IssueGroup]) -> tuple[list[IssueGroup], list[IssueGroup]]:
    """Partition *groups* into ``(errors, housekeeping)``. Errors are real dropped/failed
    lines the user may want to act on; housekeeping (``benign=True``, e.g. de-duplicated
    repeated VO) is expected pipeline behaviour and must never be counted as an "Issue"."""
    errors = [g for g in groups if not g.benign]
    housekeeping = [g for g in groups if g.benign]
    return errors, housekeeping
