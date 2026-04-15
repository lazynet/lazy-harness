<!--
Thanks for the PR. This template mirrors the format the repo's own commits
use. Delete any section that does not apply.
-->

## Summary

<!-- One or two sentences about what this PR does. Bullet points for
multiple distinct changes. Keep it tight — the commit and changelog
should be readable without opening the PR. -->

## Why

<!-- The motivation. A bug report, an ADR, a roadmap item, a user ask, or
a measurement. If this closes an issue, link it: "Closes #123". -->

## Test plan

<!-- A checklist of how this was verified end-to-end. Under strict TDD,
new code should come with tests that failed before the implementation
existed — mention the tests here. Include manual verification for any
user-visible behaviour. -->

- [ ] `uv run pytest` passes with pristine output
- [ ] `uv run ruff check src tests` passes
- [ ] `uv run --group docs mkdocs build --strict` passes (for docs changes)
- [ ] Manual end-to-end check of the user-facing behaviour (for CLI/hook/config changes)

## Followups (optional)

<!-- Anything deliberately out of scope that should be captured for later.
Links to roadmap themes or backlog items. -->
