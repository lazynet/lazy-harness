# AGENTS.md — lazy-harness

The always-loaded governance surface for every agent in this repository, and its
only instruction surface
([ADR-060](specs/adrs/060-agents-md-is-the-portable-repository-contract.md));
details live in the files it points to. Every agent finds it through the parent
directory chain: edit it when a rule changes, and never add a `CLAUDE.md` here or
in any ancestor — it shadows this file for Claude Code, and `lh repo
instructions` rejects it.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, shipped as a Python package (`lh` CLI). Python 3.11+, strict type hints, no `Any` unless unavoidable; `uv` (`uv sync` / `uv run`), `pytest`, `ruff`, MkDocs Material. Shell scripts always `set -euo pipefail`. Layout, and where a new file belongs: [`specs/workflow/layout.md`](specs/workflow/layout.md).

This is a **public repository**: README, `docs/` pages, commit messages and PR text stay generic and professional — no personal names, no pre-rename project name, no references to private predecessor repos. `specs/archive/` is the one exception: historical and frozen, per [`layout.md`](specs/workflow/layout.md). A document on *what* a user of the framework should do or see belongs in `docs/`; one on *how* we decided something, or contributor workflow, in `specs/`. The public site renders only `docs/`.

## Non-negotiables

1. **Worktrees for every code change.** Any edit touching code, tests, packaging, CI, or the governance surface (`AGENTS.md`, `specs/workflow/**`, `specs/adrs/**`, `mkdocs.yml`, `.claude/**`) goes in a worktree created as [`.claude/commands/new-worktree.md`](.claude/commands/new-worktree.md) describes, never on `main` — [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md). Doc-only edits may take the short-path in [`specs/workflow/doc-short-path.md`](specs/workflow/doc-short-path.md).
2. **Strict TDD.** No production code without a failing test written first — no exceptions, bug fixes and refactors included.
3. **Conventional commits (`type: short description`), no AI-attribution trailers.** Never skip hooks with `--no-verify`. Create new commits instead of amending published ones.
4. **The gate in [`.claude/commands/tdd-check.md`](.claude/commands/tdd-check.md) passes before every commit**, all four checks, with pristine output. Run them as that file scopes them: `uv run --frozen pytest`, `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check src tests`, `uv run --frozen --group docs mkdocs build --strict`.
5. **Versions are owned by release-please.** Never hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py`, never tag `vX.Y.Z` manually. Rules: [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md).
6. **The audit in [`.claude/commands/coherence-audit.md`](.claude/commands/coherence-audit.md) runs before a release-please release is cut**, read-only.

## What NOT to do

- Do not generate READMEs, standalone doc pages, or obvious code comments unless asked; tests are exempt, always in scope under TDD. Do not refactor outside the task or add abstractions for hypothetical needs — mention what is worth improving, do not touch it.
- Do not restate what a skill, slash command or hook already declares in its `description` — those load every session, so a copy forks the truth. This file carries only what no single description covers.

## Working in this repository

- The repository's procedures live under `.claude/commands/` as prose: `new-worktree.md`, `cleanup-worktree.md`, `tdd-check.md`, `coherence-audit.md`. An agent with no command surface reads the file and runs what it describes.
- Never change the active `gh` account. If `gh` refuses with `must be a collaborator`, stop and report which account is active.
- Check a sensitive variable for presence with `${VAR:+set}`; never print its value into a transcript or log. Printing the whole `LH_METRICS_URL` exposed the ingest token twice.

## When the agent is Claude Code

- The four procedures above are slash commands (`/new-worktree`,
  `/cleanup-worktree`, `/tdd-check`, `/coherence-audit`); prefer them.
- Strict TDD runs through the `superpowers:test-driven-development` skill;
  invoke it before the first edit of any change.

## Verification gates

Checks to run, each from a failure the compound loop recorded more than once. The evidence sits in [`specs/incidents.md`](specs/incidents.md), one section per gate **in the same order**; read it when a gate's reasoning is unclear, and update both halves together.

- **A tool's exit code is not proof of its effect.** Read the file back, re-run the loader, invoke the CLI before claiming a write, sync or deletion.
- **Config schema changes are tested through a full load cycle**: save, load, save, load any section with defaults or computed fields; test new-document and merge-on-existing separately.
- **A config schema accepting user-supplied identifiers validates them and names what it ignored.** Feed the loader a misspelled event, matcher, role or enum and assert on the diagnostic.
- **Hooks handle every exception explicitly and exit 0** — for a *blocking* hook exit 0 is the failure: exercise every exit-2 path with dependencies mocked and assert it blocks. Guard types before every `.get()`, test valid-JSON-wrong-type (null, int, list) alongside malformed JSON, and assert out-of-scope files are skipped.
- **Prose that names a mechanism is grepped against the code, in both directions.** Promised automatic behaviour must exist — delete known rows, re-invoke, and it recovers them or the doc says why not; an identifier a doc names that appears only in the new prose was invented.
- **Every path deriving a project key — memory or metrics — uses `git rev-parse --path-format=absolute --git-common-dir` and takes `.parent`**, never `--show-toplevel`. Fix them all at once, tested from a main checkout *and* a worktree.
- **Fixing a safeguard updates its documented examples *and* every diagnostic reporting on it, in the same commit**; the metric measures the expensive resource, not a proxy, validated against a distribution that breaks the assumption.
- **Parallel work is not isolated by default.** Inspect a subagent's diff before cleanup; coordinate ADR numbers, never write them in parallel.
- **An implemented hook does not run until it is wired and its binaries are reachable** — a missing `config.toml` entry may be a decision, so grep `specs/backlog.md` first. Install binaries globally: a bare command resolves from ambient `PATH`, not the `pyproject.toml` pin.
- **Behavioural automation ships with kill criteria** declared before deployment: a measured baseline, an adoption check at a fixed horizon, a removal threshold. Freeze calibration until the baseline closes, biased toward false negatives.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Delete the guard, watch it fail, restore by hand — never `git checkout`; set `PYTHONDONTWRITEBYTECODE=1` (or clear `__pycache__`) before each mutation run, because a same-size mutant reverted within one second reuses stale bytecode. Anchor `pytest.raises(match=...)` on literal config keys or enum names; pair explicit-parameter CLI tests with a parameter-less smoke test; exercise a Protocol's refusal through `NullAdapter` and assert the error's attributes.
- **One answer lives in one importable place; every path naming it derives from it or is audited against it.** Derive a list mirroring a directory from the glob, with a completeness test; where two paths answer one question, an integration test asserts they agree. Widening a type audits every path naming it *or its config*.
- **Deploying a hook is binary-first, never from a worktree.** Merge, let the release cut, `uv tool install --reinstall`, **grep site-packages** for the shipped code — only then `config.toml`, deploy, chezmoi re-add.
- **An artifact is verified by the system that consumes it; a gate script, in both directions.** Parse generator output with the real target parser on every platform; feed a checker a case it must pass *and* one it must fail. For a **merge**, check the document about to be written, and run the consumer's own validator on the shipping path, not only over fixtures.
- **A scheduled job is verified by running it through its scheduler, with its credentials resolved there** (`launchctl kickstart`, `systemctl start`). Credentials live owner-only under `<lh config dir>/secrets/`, read by `lh` (`core/secrets.py:read_metrics_secret`) — never in the plist/unit or shell init.
- **A duck-typed attribute on an injected collaborator is tested with that attribute absent**, one fake per omitted attribute per backend.
- **A cost optimisation starts from a measurement of the suspect category, not an estimate.** Diff what the first message loads against the second.
- **A claim about behaviour is verified by running the path, not by reading the name** — `--help`, docstrings, flags and config keys prove existence, not behaviour; run it, record the exit code. Design docs bind as tightly as code. For an adapter over an external binary, probe the undocumented contract *first* into `<binary>-evidence.md` and correct the design before the first test.
- **A hook that is registered is not a hook that runs.** Grep the config for its name (an explicit `[hooks.<event>].scripts` replaces `DEFAULT_HOOKS[<event>]` wholesale); declare the `matcher` with a test that fails when narrowed; read deploy output for `· <hook> omitted in '<profile>'`. Prove it by firing the real operation.
- **A hook wired into shared config lands in every profile, including the ones missing what it needs.** Exercise it in every profile first; ship its dependencies in the same change.
- **Mutation testing proves a guard has branches, not coverage.** Attack a denylist with realistic evasions — whitespace, flag reordering, alternate path spellings — and record what got through.
- **A test asserting on a rendered duration is asserting on its own runtime.** Freeze the clock and the stored timestamp to one instant, and unpin each alone to prove it load-bearing.
- **A test that kills a child to inspect the kill is racing that child's setup.** The child atomically renames a marker when ready and the deadline fires on it, never on elapsed seconds; scope the patch with `pytest.MonkeyPatch.context()`.
- **A digest or a stat identifies a path's contents, never which file the path is.** Check `os.path.islink()`/`os.readlink()` at **both** ends before concluding two layers hold one file: a read follows the link, and a write that *replaces* the path (`os.replace`, an editor save) breaks it. `deploy/skills.py::_fingerprint` branches on the link first.
