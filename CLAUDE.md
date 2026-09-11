# CLAUDE.md — lazy-harness

The always-loaded governance surface for agents working in this repository; details live in the files it points to.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, shipped as a Python package (`lh` CLI). Python 3.11+, strict type hints, no `Any` unless unavoidable; `uv` (`uv sync` / `uv run`), `pytest`, `ruff`, MkDocs Material. Shell scripts always `set -euo pipefail`.

Layout: [`specs/workflow/layout.md`](specs/workflow/layout.md). What it will not tell you — `cli/` holds one file per `lh` subcommand, `tests/` mirrors `src/lazy_harness/` one-to-one, and `specs/` splits into `adrs/` (index and status vocabulary in [`specs/adrs/README.md`](specs/adrs/README.md)), `designs/`, `workflow/` and the frozen `archive/`.

This is a **public repository**: README, `docs/` pages, commit messages and PR text stay generic and professional — no personal names, no references to private predecessor repos. `specs/archive/` is the one exception, being explicitly historical. A document on *what* a user of the framework should do or see belongs in `docs/`; one on *how* we decided something, or contributor workflow, in `specs/`. The public site renders only `docs/`.

## Non-negotiables

1. **Worktrees for every code change.** Any edit touching code, tests, packaging, CI, or the governance surface (`CLAUDE.md`, `specs/workflow/**`, `specs/adrs/**`, `mkdocs.yml`, `.claude/**`) goes in a worktree via `/new-worktree`, never on `main` — [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md). Doc-only edits may take the short-path in [`specs/workflow/doc-short-path.md`](specs/workflow/doc-short-path.md).
2. **Strict TDD**, via the `superpowers:test-driven-development` skill. This rule has no exceptions in this repo, bug fixes and refactors included.
3. **Conventional commits (`type: short description`), no AI-attribution trailers.** Never skip hooks with `--no-verify`. Create new commits instead of amending published ones.
4. **`/tdd-check` passes before every commit**, all three checks, with pristine output.
5. **Versions are owned by release-please.** Never hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py`, never tag `vX.Y.Z` manually. Rules: [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md).
6. **`/coherence-audit` runs before a release-please release is cut**, plus the one check it does not cover: the roadmap reflects completed ADR items.

## What NOT to do

- Do not generate READMEs, standalone doc pages, or obvious code comments unless asked; tests are exempt, always in scope under TDD. Do not refactor outside the task or add abstractions for hypothetical needs — mention what is worth improving, do not touch it.
- Do not reintroduce the project's pre-rename name or any individual user's name into public surface: `README.md`, `docs/index.md`, `docs/why/*`, `docs/getting-started/*`, `docs/reference/*`, `docs/architecture/overview.md`, `mkdocs.yml`. Only `specs/archive/**` may carry that history — and that tree is frozen on purpose, so do not edit it to "fix" stale references, paths or nomenclature either. Moving those files in a wider restructure is fine; editing their content is not.
- Do not restate in this file what a skill, slash command, or hook already declares in its own `description`. Those descriptions load every session regardless; the copy here only costs tokens and forks the truth. `CLAUDE.md` carries the combinations and workflows no single description covers.


## Verification gates

Each comes from a failure the compound loop recorded more than once: checks to run, not principles to agree with. The incident behind each one is in [`specs/incidents.md`](specs/incidents.md), in this order — read it when a gate's reasoning is unclear, and update both halves together.

- **A tool's exit code is not proof of its effect.** Read the file back, re-run the loader, invoke the CLI — including before claiming a write, sync or deletion happened.
- **Config schema changes are tested through a full load cycle**, not a successful write. Sections with defaults or computed fields get a round trip — save, load, save, load. Test the new-document and merge-on-existing paths separately.
- **Hooks handle every exception explicitly and exit 0.** Inverted for a *blocking* hook, where exit 0 is the failure: exercise every exit-2 path with dependencies mocked away and assert it still blocks. Guard types before every `.get()`, test valid-JSON-wrong-type (null, int, list where a dict is expected) alongside malformed JSON, and assert out-of-scope files are skipped.
- **Prose that names a mechanism is grepped against the code, in both directions.** A config field promising automatic behaviour must have it implemented, and a docstring promising a deterministic operation is held to the same standard — delete known rows, re-invoke, and either it recovers them or the docstring says why not. Conversely, grep every identifier a doc names: if it appears only in the new prose, it was invented.
- **Every path deriving a project key — memory or metrics — uses `git rev-parse --path-format=absolute --git-common-dir` and takes `.parent`**, never `--show-toplevel`. Fix them all at once, tested from a main checkout *and* a worktree.
- **Fixing a safeguard updates its documented examples *and* every diagnostic that reports on it, in the same commit**, and the metric measures the expensive resource rather than a proxy. Validate the metric against a distribution that breaks the assumption.
- **Parallel work is not isolated by default.** Inspect a subagent's diff before cleanup, and coordinate ADR numbers rather than writing them in parallel.
- **An implemented hook does not run until it is wired and its binaries are reachable** — but a missing `config.toml` entry may be a decision rather than an oversight, so grep `specs/backlog.md` before wiring one. Install binaries globally: a bare command name resolves from ambient `PATH`, never the `pyproject.toml` pin.
- **A static list that should mirror a directory is derived from it, with a test asserting completeness against the glob.**
- **Behavioural automation ships with kill criteria** declared before deployment: a measured baseline, an adoption check at a fixed horizon, and the threshold below which it is *removed*. The calibration a baseline is read against is frozen until that baseline closes, so start biased toward false negatives.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Delete the guard, watch a test fail, restore by editing the file back by hand — never `git checkout`, which reverts the uncommitted implementation too. Anchor `pytest.raises(match=...)` on literal config keys or enum names, never a substring a `tmp_path` or traceback could also carry. Pair each explicit-parameter CLI test with a parameter-less smoke test.
- **Every reader and writer of a config-derived path — or of a derived answer — resolves it the same way.** Where two paths answer one question, an integration test invokes both and asserts they agree, and the deciding rules live in one importable place.
- **Widening a type means auditing every path that names it** — for a pluggable protocol, every code path naming its type or its config, not just the `Protocol` methods.
- **Deploying a hook is binary-first, never from a worktree.** Merge, let the release cut, `uv tool install --reinstall`, then **grep site-packages** to confirm the code shipped — only then touch `config.toml`, deploy, re-add to chezmoi.
- **An artifact is verified by the system that consumes it, not by the test that wrote it; a gate script, in both directions.** Parse generator output with the real target parser and exercise platform-specific paths on every target. Feed a checker a case it must pass *and* one it must fail.
- **A scheduled job is verified by running it through its scheduler, with its credentials resolved there** — `launchctl kickstart` or `systemctl start`, never code inspection plus a file-existence check. Credentials belong in the job definition (plist `EnvironmentVariables`, systemd `EnvironmentFile`), never in shell init, which no scheduler reads.
- **A duck-typed attribute on an injected collaborator is tested with that attribute absent.** Exercise each backend with a fake omitting each attribute.
- **A cost optimisation starts from a measurement of the suspect category, not an estimate.** Diff what the first message loads against the second before spending effort.
