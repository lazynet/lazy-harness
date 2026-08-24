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

- **A tool's exit code is not proof of its effect.** `uv tool install --force` reused a cached wheel; a config generator wrote valid TOML that the loader then rejected. Verify the effect — read the file back, re-run the loader, invoke the CLI — before reporting success.
- **Config schema changes are tested through a full load cycle**, not just a successful write. A test asserting the file was written passes happily while the generated config is unloadable. Profile validation checks *schema*, not only JSON parsability: a null hook matcher parses fine and makes the consuming agent discard the entire settings file. Any section with defaults or computed fields also gets a **round trip** — save, load, save, load — because a deserializer that supplies a default the serializer omits drops it silently on the next rewrite. Merge-on-write has two paths, not one: the new-document path writes every required field, the merge-on-existing path may skip unchanged defaults, and each is tested separately — an optimisation that skipped a required field left merges onto a missing or corrupted file unloadable, and the create path has already dodged the mode-preserving `chmod` the merge path applied.
- **Hooks handle every exception explicitly and exit 0.** The framework does not suppress them for you: an unhandled error escapes to the subprocess and crashes the chain instead of degrading.
- **Anchor `pytest.raises(match=...)` on literal config keys or enum names**, never a substring that could also appear in a `tmp_path` or a traceback.
- **A config field that promises automatic behaviour must have that behaviour implemented.** Grep for it at review time. `auto_rebuild_on_commit` shipped for months doing nothing while looking like a fulfilled contract.
- **Every path deriving a project key for memory uses `git rev-parse --path-format=absolute --git-common-dir` and takes `.parent`**, never `--show-toplevel`. Worktrees otherwise fragment `decisions.jsonl` into directories nothing ever reads. When fixing one such path, grep for all of them and test from both the main checkout and a worktree — a half-applied canonicalisation leaves some tools reading the right directory and others the wrong one.
- **Fixing a safeguard updates its documented examples *and* every diagnostic that reports on it, in the same commit.** Spec examples that outlive the behaviour they describe become a false source of truth, and a diagnostic still measuring the old dimension reports false green.
- **Safeguard metrics measure the expensive resource, not a proxy for it.** A memory-size hook capped lines while the cost was bytes, and waved through a 20KB file holding 67 of them. Identify the resource that actually costs (bytes, tokens, time), then validate the metric against a distribution that breaks the assumption.
- **Verify subagent scope before cleanup.** Inspect the diff to confirm edits stayed inside the intended worktree — isolation is not implicit.
- **ADR numbers are coordinated, never written in parallel.** Two worktrees creating ADRs at once collide on the sequence.
- **An implemented hook does not run until it is wired and its binaries are reachable.** Registration in `_BUILTIN_HOOKS` without a `config.toml [hooks.*]` entry passes every test and never executes. A required binary living in a peer project's virtualenv is invisible to a hook running from the installed tool's environment — install it globally.
- **A hook's tests cover the wrong-type input and the out-of-scope file, not only the happy path.** Exception handling copied between hooks carries the original's latent bugs: guard types before every `.get()`, and test valid-JSON-wrong-type (null, int, list where a dict is expected) alongside malformed JSON. Where a hook has a declared scope, assert that files outside it are skipped — positive-only tests cannot see scope divergence.
- **CLI tests pair each explicit-parameter unit test with a parameter-less smoke test.** Always injecting the parameter leaves the default-resolution path completely untested; two `Path.cwd()` bugs survived years of green suites that way.
- **Never run `uv` against live profiles from a worktree.** Config generators embed the invoking interpreter's path, so a worktree venv gets baked into deployed hooks and breaks silently at cleanup. `uv` operations belong in the root checkout — running them from a worktree has also degraded `uv.lock`. Deploy with the installed tool, never the development runner.
- **Behavioural automation ships with kill criteria.** Anything that injects requests or fires on events declares, before deployment: a measured baseline, an adoption check at a fixed horizon, and the threshold below which it is *removed* rather than supplemented with another trigger. A documented practice without enforcement runs around 60% non-compliance; a mechanism nobody adopts is debt wearing the costume of a feature.
- **Assumptions about tool behaviour are verified end-to-end in the target context.** Grep, docs, and a confident mental model are necessary and insufficient. Invoke the tool, in the environment that will run it, before a design depends on the answer.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Prove it by deleting the guard, running the suite, and watching a test fail — then restore. Broad `except` clauses are what make this invisible: with the type guard removed, four tests written to prove that guard still passed, because the handler turned the `AttributeError` into the same exit code as the correct path. The same blindness has two other shapes: an expected value reverse-calculated from the implementation's own assumption confirms the bug instead of catching it — a capture-rate check read 20% as green that way — and an assertion mirroring the code's own predicate asserts nothing at all. Undo the mutation by editing the file back by hand, never with `git checkout`: the work is uncommitted in a worktree, so a checkout reverts the implementation along with the mutation.
- **Documentation of mechanics cites the source.** Every identifier a doc names — env var, table, path, field, function — must appear in the code; grep each one, and if it appears only in the new prose, it was invented. Plausibility is the danger, not carelessness: `loop_events.jsonl` and `CLAUDE_DATA_DIR` both pattern-matched this repo's conventions perfectly and neither existed.
- **Every reader and writer of a config-derived path — or of a derived answer — resolves it the same way.** Readers here honour `[monitoring] db` before falling back to the data dir; two hooks that skipped that lookup would have written a file nothing reads — zero forever, with no error. Grep all sides of a path before shipping a feature that spans components. The same holds for state: when two code paths answer the same question about configuration, an integration test invokes both with identical input and asserts they agree, and the deciding rules live in one importable place. Copy-pasted rules are how the two answers diverge — one path knew about agent-dependent filtering and the other did not.
- **Widening a type annotation requires auditing the body against every member of the new union.** An annotation that promises more than the code implements is worse than a narrow one that is merely imprecise: it advertises a capability that fails at runtime. `path: Path` → `Path | str` without coercing left `path.parent` raising on every string but one.
- **Repo patterns outrank the text of a plan.** A plan is task-scoped; a pattern already applied across a module is a durable decision. When a review finds the plan asking for something the surrounding code does differently, the pattern wins — fix it in place and record why.
- **Deploying a hook is binary-first.** Merge, let the release cut, `uv tool install --reinstall`, then **grep site-packages** to confirm the code is in the installed tool — only then touch `config.toml`, deploy, and re-add to chezmoi. Wiring a new event before the binary ships it runs the new config against the old code. Repository state and deployed state diverge the moment a release is cut; verify the binary, never the checkout.
- **A calibration that a baseline will be read against is frozen until the baseline closes.** Widening a matcher or lowering a threshold mid-measurement invalidates the comparison the measurement exists to enable. Start conservative — biased toward false negatives — and expand only after the numbers justify it.
- **An artifact is verified by the system that consumes it, not by the test that wrote it.** This repo generates launchd plists, systemd units, cron lines and `index.yml` for four foreign parsers, and every one of them has accepted a syntactically valid file and rejected it at load time. A generator's tests parse its output with the real target parser, and any generator whose output embeds a platform-specific path is exercised on every target — a qmd template that passed every check indexed zero documents on the Linux container because a macOS path was baked in, with no error signal anywhere.
- **A duck-typed attribute on an injected collaborator is tested with that attribute absent.** The scheduler backends read a runner's result with `getattr(proc, "stdout", "")` and `getattr(proc, "returncode", 0)`, so a fake whose result object omits one of them silently yields the default — which reads as success, and the test then passes for the wrong reason. Exercise each backend with a fake that omits each attribute, not only with one that supplies them all.
- **A gate script is verified in both directions before it is trusted.** Feed it a case it must pass and a case it must fail, and confirm it reports each correctly. A `set -e` interaction once made a checker evaluate 1 of 11 views and exit 0, reporting green for work it never looked at — a gate that cannot fail invalidates every gate that leans on it.

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
