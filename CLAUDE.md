# CLAUDE.md — lazy-harness

Instructions for Claude Code and other compatible agents working in this repository. This file is the always-loaded governance surface; details live in the files it points to.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, distributed as a Python package (`lh` CLI). Code lives in `src/lazy_harness/`, tests mirror it one-to-one in `tests/`, internal design artifacts in `specs/`, and the public docs site is built from `docs/` with MkDocs Material.

This is a **public repository**. Public surface (README, `docs/` pages, commit messages, PR text) stays generic and professional — no personal names, no references to private predecessor repos. The one exception is `specs/archive/`, which is explicitly historical material.

**`specs/` vs `docs/`:** if a document explains *what* a user of the framework should do or see, it belongs in `docs/`. If it explains *how* we decided to build something, or captures contributor workflow, it belongs in `specs/`. The public site only renders `docs/`.

## Stack (one-liners)

- **Language:** Python 3.11+, strict type hints, no `Any` unless unavoidable.
- **Packaging:** `uv`. Dependencies in `pyproject.toml`. Use `uv sync` / `uv run`.
- **Tests:** `pytest` via `uv run pytest`. Every `src/lazy_harness/` module has a mirrored test file.
- **Lint/format:** `ruff` (config in `pyproject.toml`).
- **Docs site:** MkDocs Material. `uv run --group docs mkdocs build --strict`.
- **Shell scripts:** `set -euo pipefail` always.
- **Containers:** Docker when runtime isolation is needed.

## Non-negotiables

1. **Worktrees for every code change.** Any edit that touches code, tests, packaging, CI, or the governance surface (`CLAUDE.md`, `specs/workflow/**`, `specs/adrs/**`, `mkdocs.yml`, `.claude/**`) is made in a `.worktrees/<short-name>` worktree on a `<type>/<short-name>` branch, never directly on `main`. Full rules and the `/new-worktree` + `/cleanup-worktree` slash commands: [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md). Documentation-only edits may use the short-path in [`specs/workflow/doc-short-path.md`](specs/workflow/doc-short-path.md).
2. **Strict TDD.** No production code is written without a failing test that exercises it first. Follow the `superpowers:test-driven-development` skill exactly — invoke it via the `Skill` tool when you start any code change. This rule has no exceptions in this repo, including bug fixes and refactors.
3. **Conventional commits, no AI trailers.** Format: `type: short description` (e.g. `fix: handle missing profile dir`). Do **not** add `Co-Authored-By` or any AI-attribution trailers. Do **not** skip hooks with `--no-verify`. Create new commits instead of amending published ones.
4. **Pre-commit verification is all three checks.** Run `/tdd-check` before every commit: `uv run pytest`, `uv run ruff check src tests`, and `uv run --group docs mkdocs build --strict` must all pass with pristine output.
5. **Versions are owned by release-please.** Never hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py`, never tag `vX.Y.Z` manually. Mechanism and commit-type rules: [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md).
6. **Docs coherence is audited before every release.** Before a release-please release is cut, verify the CLI reference matches implemented commands, hooks docs match registered hooks, memory architecture docs match compound-loop artifacts, and the roadmap reflects completed ADR items. `uv run --group docs mkdocs build --strict` must pass.

## What NOT to do

- Do not write production code without a failing test first. See non-negotiable #2.
- Do not generate READMEs, standalone documentation pages, or obvious code comments unless explicitly asked. Tests are always in scope under TDD and exempt from this rule.
- Do not refactor code that was not part of the task. If you spot something worth improving, mention it; do not touch it.
- Do not introduce abstractions for hypothetical future needs. Three similar lines beats a premature abstraction.
- Do not reintroduce references to the project's pre-rename name or any individual user's name into public surface: `README.md`, `docs/index.md`, `docs/why/*`, `docs/getting-started/*`, `docs/reference/*`, `docs/architecture/overview.md`, `mkdocs.yml`. Only `specs/archive/**` is allowed to carry that history.
- Do not edit files in `specs/archive/**` to "fix" historical references, stale paths, or outdated nomenclature. That tree is frozen on purpose. Moving files as part of a wider restructure is fine; editing their content is not.
- Do not claim a persistence operation (file write, sync, deletion) happened without verifying it with explicit file or git output.
- Do not commit secrets, credentials, or personal identifying information.

## Verification gates

Each of these comes from a failure the compound loop recorded more than once. They are checks to run, not principles to agree with.

- **A tool's exit code is not proof of its effect.** `uv tool install --force` reused a cached wheel; a config generator wrote valid TOML the loader then rejected. Read the file back, re-run the loader, invoke the CLI.
- **Config schema changes are tested through a full load cycle**, not a successful write. Validation checks *schema*, not JSON parsability: a null hook matcher parses fine and makes the agent discard the entire settings file. Any section with defaults or computed fields also gets a **round trip** — save, load, save, load. Test the new-document path and the merge-on-existing path separately: each has skipped a required field the other supplied, and the create path has dodged the mode-preserving `chmod` the merge path applied.
- **Hooks handle every exception explicitly and exit 0.** Unhandled errors escape to the subprocess and crash the chain instead of degrading.
- **Anchor `pytest.raises(match=...)` on literal config keys or enum names**, never a substring that could also appear in a `tmp_path` or a traceback.
- **A config field that promises automatic behaviour must have that behaviour implemented.** Grep for it at review time — `auto_rebuild_on_commit` shipped for months doing nothing.
- **Every path deriving a memory project key uses `git rev-parse --path-format=absolute --git-common-dir` and takes `.parent`**, never `--show-toplevel`. Worktrees otherwise fragment `decisions.jsonl` into directories nothing reads. When fixing one, grep for all of them and test from both the main checkout and a worktree.
- **Fixing a safeguard updates its documented examples *and* every diagnostic that reports on it, in the same commit.** Stale examples become a false source of truth; a diagnostic measuring the old dimension reports false green.
- **Safeguard metrics measure the expensive resource, not a proxy for it.** A memory-size hook capped lines while the cost was bytes, waving through a 20KB file. Validate the metric against a distribution that breaks the assumption.
- **Verify subagent scope before cleanup.** Inspect the diff — isolation is not implicit.
- **ADR numbers are coordinated, never written in parallel.** Two worktrees collide on the sequence.
- **An implemented hook does not run until it is wired and its binaries are reachable.** Registration in `_BUILTIN_HOOKS` without a `config.toml [hooks.*]` entry passes every test and never executes. A binary in a peer project's virtualenv is invisible to a hook running from the installed tool — install it globally.
- **A hook's tests cover the wrong-type input and the out-of-scope file, not only the happy path.** Guard types before every `.get()`; test valid-JSON-wrong-type (null, int, list where a dict is expected) alongside malformed JSON; assert files outside a declared scope are skipped.
- **CLI tests pair each explicit-parameter unit test with a parameter-less smoke test.** Always injecting the parameter leaves default resolution untested — two `Path.cwd()` bugs survived years of green suites that way.
- **Never run `uv` against live profiles from a worktree.** Config generators embed the invoking interpreter's path, baking a worktree venv into deployed hooks; it has also degraded `uv.lock`. Deploy with the installed tool, never the development runner.
- **Behavioural automation ships with kill criteria**, declared before deployment: a measured baseline, an adoption check at a fixed horizon, and the threshold below which it is *removed*. A documented practice without enforcement runs around 60% non-compliance.
- **Assumptions about tool behaviour are verified end-to-end in the target context.** Grep, docs, and a confident mental model are necessary and insufficient.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Prove it by deleting the guard and watching a test fail, then restore by editing the file back by hand — never `git checkout`, which reverts the uncommitted implementation too. Broad `except` clauses make this invisible: with a type guard removed, four tests written to prove it still passed. Two other shapes of the same blindness: an expected value reverse-calculated from the implementation confirms the bug instead of catching it, and an assertion mirroring the code's own predicate asserts nothing.
- **Documentation of mechanics cites the source.** Grep every identifier a doc names — env var, table, path, field, function. If it appears only in the new prose, it was invented. `loop_events.jsonl` and `CLAUDE_DATA_DIR` both pattern-matched this repo's conventions perfectly and neither existed.
- **Every reader and writer of a config-derived path — or of a derived answer — resolves it the same way.** Readers honour `[monitoring] db` before falling back to the data dir; a hook skipping that lookup writes a file nothing reads — zero forever, no error. When two code paths answer the same question, an integration test invokes both with identical input and asserts they agree, and the deciding rules live in one importable place.
- **Widening a type annotation requires auditing the body against every member of the new union.** `path: Path` → `Path | str` without coercing left `path.parent` raising on every string but one.
- **Repo patterns outrank the text of a plan.** A plan is task-scoped; a pattern already applied across a module is a durable decision. Fix it in place and record why.
- **Deploying a hook is binary-first.** Merge, let the release cut, `uv tool install --reinstall`, then **grep site-packages** to confirm the code shipped — only then touch `config.toml`, deploy, and re-add to chezmoi. Repository state and deployed state diverge the moment a release is cut.
- **A calibration that a baseline will be read against is frozen until the baseline closes.** Widening a matcher or lowering a threshold mid-measurement invalidates the comparison. Start biased toward false negatives.
- **An artifact is verified by the system that consumes it, not by the test that wrote it.** This repo generates launchd plists, systemd units, cron lines and `index.yml` for four foreign parsers, and every one has accepted a syntactically valid file and rejected it at load time. Parse generator output with the real target parser, and exercise any platform-specific path on every target — a qmd template that passed every check indexed zero documents on Linux.
- **A duck-typed attribute on an injected collaborator is tested with that attribute absent.** Scheduler backends read `getattr(proc, "stdout", "")` and `getattr(proc, "returncode", 0)`, so a fake omitting one silently yields the default — which reads as success. Exercise each backend with a fake that omits each attribute.
- **A gate script is verified in both directions before it is trusted.** Feed it a case it must pass and a case it must fail. A `set -e` interaction once made a checker evaluate 1 of 11 views and exit 0, reporting green for work it never looked at.

## Where things live

High-level map: [`specs/workflow/layout.md`](specs/workflow/layout.md). Short form:

- `src/lazy_harness/<area>/` → code, one file per `lh` subcommand in `cli/`
- `tests/` → mirrors `src/lazy_harness/` one-to-one
- `docs/` → public MkDocs site
- `specs/adrs/` → active decision records (see [`specs/adrs/README.md`](specs/adrs/README.md) for the index and status vocabulary)
- `specs/designs/` → long-form design specs
- `specs/workflow/` → internal contributor workflow (worktrees, release flow, layout)
- `specs/archive/` → frozen historical material, do not edit

## Slash commands available in this repo

- `/new-worktree <type>/<short-name>` — create a worktree and branch with correct naming. [`.claude/commands/new-worktree.md`](.claude/commands/new-worktree.md)
- `/cleanup-worktree <short-name>` — remove a merged worktree and its branch after verifying it was merged. [`.claude/commands/cleanup-worktree.md`](.claude/commands/cleanup-worktree.md)
- `/tdd-check` — run pytest + ruff + mkdocs build as the pre-commit gate. [`.claude/commands/tdd-check.md`](.claude/commands/tdd-check.md)
- `/coherence-audit` — read-only audit of semantic drift between ADRs/backlog and the code they describe. [`.claude/commands/coherence-audit.md`](.claude/commands/coherence-audit.md)
