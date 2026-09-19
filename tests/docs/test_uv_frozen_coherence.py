"""Every `uv run` the repo's own automation prescribes carries `--frozen`.

Measured 2026-09-14: a plain `uv run` issued after any edit under `src/`
discards the committed lockfile and rewrites a reduced one — 54 packages down
to 16, `revision = 3` dropped and every `upload-time` stripped, 817 lines
deleted. `uv run -v` names the reason:

    DEBUG Ignoring existing lockfile due to mismatched dev dependencies
    for: `lazy-harness==0.63.0`

Edit a source file, then run the tests, is this repo's TDD cycle, so every
worktree accumulates a degraded `uv.lock` that the next commit can carry in
unnoticed. Three of them did in one session.

`uv run --frozen` was verified to prevent it, in both directions: with the flag
the lock stays byte-identical across the same edit, without it the rewrite
happens every time. `--group dev` also avoids it, and declaring
`[tool.uv] default-groups` does *not* — measured, not assumed — so the flag is
the mechanism rather than a configuration fix.

This is a separate defect from the `release-please` item in `specs/backlog.md`,
which describes the lock's version line lagging a release and dirtying the tree
*even with* `--frozen` through the editable install. That one rewrites one line;
this one discards the file. Both can be true; only this one has a fix here.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The surfaces that prescribe the command a human or an agent then runs: the
# slash commands, CI, the PR checklist, and the workflow rules.
#
# `specs/workflow/` belongs here and the first revision of this file missed it,
# which let `doc-short-path.md` keep prescribing a gate command that rewrites
# the lockfile. `specs/designs/` and `specs/adrs/` stay out for a reason that
# does not apply to workflow rules: they record what was decided and run at the
# time, and editing them to satisfy a present-day rule would be the opposite of
# a record.
#
# `AGENTS.md` also names bare `uv run` as a tool, alongside its gate commands;
# scanning that overview with this line-based matcher would be a false positive.
AUTOMATION_GLOBS = (
    ".claude/commands/*.md",
    ".github/workflows/*.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "specs/workflow/*.md",
    "CONTRIBUTING.md",
)

_UV_RUN = re.compile(r"uv run(?P<flags>(?:\s+--?[\w-]+(?:[= ][^\s`]+)?)*)")


def _automation_files() -> list[Path]:
    files: list[Path] = []
    for pattern in AUTOMATION_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def _offenders(text: str) -> list[str]:
    """Every `uv run` invocation in `text` that does not pass `--frozen`.

    Reported as the rest of its line rather than the matched prefix: a bare
    `uv run` tells whoever reads the failure nothing about which of the three
    gate commands to fix.
    """
    found: list[str] = []
    for line in text.splitlines():
        for match in _UV_RUN.finditer(line):
            if "--frozen" in match.group("flags"):
                continue
            found.append(line[match.start() :].strip().strip("`").strip())
    return found


def test_the_automation_surfaces_are_actually_found() -> None:
    """Guard against the glob silently matching nothing.

    Without this the offender test passes vacuously the day a file moves, and a
    green suite would mean 'we looked nowhere' rather than 'we found nothing'.
    """
    files = _automation_files()

    assert len(files) >= 4, f"expected the slash commands, CI and the PR template, got {files}"
    names = {f.name for f in files}
    assert "tdd-check.md" in names
    assert "tests.yml" in names


def test_every_prescribed_uv_run_is_frozen() -> None:
    """A `uv run` without `--frozen` rewrites uv.lock after any source edit."""
    offenders: dict[str, list[str]] = {}
    for path in _automation_files():
        found = _offenders(path.read_text())
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert offenders == {}, (
        "these invocations rewrite uv.lock when run after a source edit; "
        f"add --frozen:\n{offenders}"
    )


def test_the_check_rejects_a_bare_uv_run() -> None:
    """The checker must fail on the shape it exists to catch.

    Paired with the test above so neither direction is assumed: that one proves
    the repo is clean, this one proves a dirty repo would not be.
    """
    assert _offenders("uv run pytest") == ["uv run pytest"]
    assert _offenders("uv run --group docs mkdocs build") == ["uv run --group docs mkdocs build"]
    assert _offenders("  run: uv run --python 3.11 pytest") == ["uv run --python 3.11 pytest"]


def test_the_check_accepts_frozen_invocations() -> None:
    """--frozen satisfies it wherever it sits among the other flags."""
    assert _offenders("uv run --frozen pytest") == []
    assert _offenders("uv run --frozen --group docs mkdocs build --strict") == []
    assert _offenders("uv run --python 3.11 --frozen pytest") == []
