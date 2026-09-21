# AGENTS.md — lazy-harness

The always-loaded governance surface for every agent working in this repository,
whatever binary runs it; details live in the files it points to. Every
non-negotiable, prohibition and verification gate below applies to all of them.

This file is canonical and is the only repository instruction surface
([ADR-060](specs/adrs/060-agents-md-is-the-portable-repository-contract.md)).
Both Claude Code and Codex discover it through the parent directory chain;
`lh repo instructions` rejects `CLAUDE.md` files that would shadow it.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, shipped as a Python package (`lh` CLI). Python 3.11+, strict type hints, no `Any` unless unavoidable; `uv` (`uv sync` / `uv run`), `pytest`, `ruff`, MkDocs Material. Shell scripts always `set -euo pipefail`. Layout, and where a new file belongs: [`specs/workflow/layout.md`](specs/workflow/layout.md).

This is a **public repository**: README, `docs/` pages, commit messages and PR text stay generic and professional — no personal names, no references to private predecessor repos. `specs/archive/` is the one exception, being explicitly historical. A document on *what* a user of the framework should do or see belongs in `docs/`; one on *how* we decided something, or contributor workflow, in `specs/`. The public site renders only `docs/`.

## Non-negotiables

1. **Worktrees for every code change.** Any edit touching code, tests, packaging, CI, or the governance surface (`AGENTS.md`, `CLAUDE.md`, `specs/workflow/**`, `specs/adrs/**`, `mkdocs.yml`, `.claude/**`) goes in a worktree created as [`.claude/commands/new-worktree.md`](.claude/commands/new-worktree.md) describes, never on `main` — [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md). Doc-only edits may take the short-path in [`specs/workflow/doc-short-path.md`](specs/workflow/doc-short-path.md).
2. **Strict TDD.** No production code without a failing test written first. This rule has no exceptions in this repo, bug fixes and refactors included.
3. **Conventional commits (`type: short description`), no AI-attribution trailers.** Never skip hooks with `--no-verify`. Create new commits instead of amending published ones.
4. **The gate in [`.claude/commands/tdd-check.md`](.claude/commands/tdd-check.md) passes before every commit**, all four checks, with pristine output. The fourth is `ruff format --check`; gating only on `ruff check` lets layout drift until it lands on top of a logic change. Run them as that file scopes them: `uv run --frozen pytest -q`, `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check src tests`, `uv run --frozen --group docs mkdocs build --strict`.
5. **Versions are owned by release-please.** Never hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py`, never tag `vX.Y.Z` manually. Rules: [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md).
6. **The audit in [`.claude/commands/coherence-audit.md`](.claude/commands/coherence-audit.md) runs before a release-please release is cut**, read-only, plus the one check it does not cover: the roadmap reflects completed ADR items.

## What NOT to do

- Do not generate READMEs, standalone doc pages, or obvious code comments unless asked; tests are exempt, always in scope under TDD. Do not refactor outside the task or add abstractions for hypothetical needs — mention what is worth improving, do not touch it.
- Do not reintroduce the project's pre-rename name or any individual user's name into public surface (`README.md`, `docs/**`, `mkdocs.yml`). Only `specs/archive/**` carries that history, and it is frozen — the rule for it is in [`layout.md`](specs/workflow/layout.md).
- Do not restate here what a skill, slash command or hook already declares in its own `description`: those load every session anyway, so a copy only costs tokens and forks the truth. This file carries the combinations no single description covers.

## Working in this repository

- The repository's own procedures live under `.claude/commands/` as prose: `new-worktree.md`, `cleanup-worktree.md`, `tdd-check.md` and `coherence-audit.md`. An agent with no native command surface reads the file and runs the git or shell commands it describes.
- Never change the active `gh` account. If `gh` refuses with `must be a collaborator`, stop and report which account is active.
- `AGENTS.md` is the file to edit when a rule changes. Do not add `CLAUDE.md`;
  on Claude Code it shadows the portable parent-chain discovery this contract
  depends on.

## When the agent is Claude Code

- The four procedures named above are slash commands: `/new-worktree`,
  `/cleanup-worktree`, `/tdd-check` and `/coherence-audit`. Prefer them over
  running the underlying commands by hand.
- Strict TDD runs through the `superpowers:test-driven-development` skill;
  invoke it before the first edit of any change.

## Verification gates

Checks to run, not principles to agree with — each came from a failure the compound loop recorded more than once. The evidence sits in [`specs/incidents.md`](specs/incidents.md), one section per gate **in the same order**; read it when a gate's reasoning is unclear, and update both halves together.

- **A tool's exit code is not proof of its effect.** Read the file back, re-run the loader, invoke the CLI before claiming a write, sync or deletion happened.
- **Config schema changes are tested through a full load cycle**, not a successful write. Round-trip any section with defaults or computed fields — save, load, save, load — and test the new-document and merge-on-existing paths separately.
- **A config schema accepting user-supplied identifiers validates them explicitly and names what it ignored.** Event names, matchers, roles, enums: feed the loader a misspelled one and assert on the diagnostic.
- **Hooks handle every exception explicitly and exit 0**, inverted for a *blocking* hook, where exit 0 is the failure: exercise every exit-2 path with dependencies mocked away and assert it still blocks. Guard types before every `.get()`, test valid-JSON-wrong-type (null, int, list for a dict) alongside malformed JSON, and assert out-of-scope files are skipped.
- **Prose that names a mechanism is grepped against the code, in both directions.** A config field or docstring promising automatic or deterministic behaviour must have it implemented — delete known rows, re-invoke, and either it recovers them or the doc says why not. Conversely, grep every identifier a doc names: if it appears only in the new prose, it was invented.
- **Every path deriving a project key — memory or metrics — uses `git rev-parse --path-format=absolute --git-common-dir` and takes `.parent`**, never `--show-toplevel`. Fix them all at once, tested from a main checkout *and* a worktree.
- **Fixing a safeguard updates its documented examples *and* every diagnostic that reports on it, in the same commit**, and the metric measures the expensive resource, not a proxy — validated against a distribution that breaks the assumption.
- **Parallel work is not isolated by default.** Inspect a subagent's diff before cleanup, and coordinate ADR numbers rather than writing them in parallel.
- **An implemented hook does not run until it is wired and its binaries are reachable** — but a missing `config.toml` entry may be a decision, so grep `specs/backlog.md` before wiring one. Install binaries globally: a bare command name resolves from ambient `PATH`, never the `pyproject.toml` pin.
- **Behavioural automation ships with kill criteria** declared before deployment: a measured baseline, an adoption check at a fixed horizon, and the threshold below which it is *removed*. Freeze the calibration until that baseline closes, so start biased toward false negatives.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Delete the guard, watch a test fail, restore by hand — never `git checkout`, which reverts the uncommitted implementation too. Anchor `pytest.raises(match=...)` on literal config keys or enum names. Pair each explicit-parameter CLI test with a parameter-less smoke test. Exercise a Protocol's refusal path through the shipped sentinel (`NullAdapter`) and assert the error's structured attributes.
- **One answer lives in one importable place; every path naming it is derived from it or audited against it.** A static list mirroring a directory is derived from the glob, with a test asserting completeness. Where two paths answer one question, an integration test invokes both and asserts they agree. Widening a type audits every path naming that type *or its config*, not just the `Protocol` methods.
- **Deploying a hook is binary-first, never from a worktree.** Merge, let the release cut, `uv tool install --reinstall`, then **grep site-packages** to confirm the code shipped — only then touch `config.toml`, deploy, re-add to chezmoi.
- **An artifact is verified by the system that consumes it, not by the test that wrote it; a gate script, in both directions.** Parse generator output with the real target parser and exercise platform-specific paths on every target. Feed a checker a case it must pass *and* one it must fail. Where the artifact is a **merge**, check the document about to be written, not the one read: an input that passes says nothing about the output, and an input that fails may be one the merge repairs. Port the consumer's own validator onto the shipping path — a copy running only over the repo's fixtures never sees a real machine's merge.
- **A scheduled job is verified by running it through its scheduler, with its credentials resolved there** — `launchctl kickstart` or `systemctl start`, never code inspection plus a file-existence check. Credentials belong in the job definition (plist `EnvironmentVariables`, systemd `EnvironmentFile`), never in shell init, which no scheduler reads.
- **A duck-typed attribute on an injected collaborator is tested with that attribute absent.** Exercise each backend with a fake omitting each one.
- **A cost optimisation starts from a measurement of the suspect category, not an estimate.** Diff what the first message loads against the second before spending effort.
- **A claim about behaviour is verified by running the path, not by reading the name.** `--help` text, a docstring, a flag name and a config key prove a thing exists, never what it does — run the command and record the exit code, evaluate the expression, open the file. Design documents are bound as tightly as code. For an adapter over an external binary the probes come *first*: run them for the undocumented contract (payload schema, command parsing, response format, state keying), record observed-vs-spec in `<binary>-evidence.md`, and correct the design before the first test.
- **A hook that is registered is not a hook that runs.** Three narrowings sit between a builtin and a tool call. Grep the config for the hook's own name — an explicit `[hooks.<event>].scripts` list replaces `DEFAULT_HOOKS[<event>]` wholesale. Declare the `matcher`, and assert a test fails when it is narrowed. Read the deploy's own output for `· <hook> omitted in '<profile>'`. Prove all three by firing the real operation, never by reading the registry.
- **A hook wired into shared config lands in every profile, including the ones missing what it needs** — `config.toml` is shared, identity is per profile. Exercise it in every profile before wiring it, and ship what it depends on in the same change.
- **Mutation testing proves a guard has branches, not that it has coverage.** Attack a denylist with realistic evasions of its own patterns — whitespace, flag reordering, alternate path spellings — and record what got through.
- **A test asserting on a rendered duration is asserting on its own runtime** — a stopwatch budget on the code under test, not a clock edge. Freeze both ends of the subtraction, the clock and the stored timestamp, to the same instant, and unpin each half alone to prove it was load-bearing.
- **A test that kills a child in order to inspect what the kill did is racing that child's setup.** Have the child atomically rename a marker when its setup is done and fire the deadline on that mark, never on elapsed seconds — and scope the patch with `pytest.MonkeyPatch.context()`, because the rest of the test has subprocesses of its own.
- **A digest or a stat identifies a path's contents, never which file the path is.** `os.path.islink()` and `os.readlink()` at **both** ends before concluding two layers hold one file, or that a duplicate is impossible — a read, stat or hash follows the link and says nothing about the link still being there, and a write that *replaces* the path (`os.replace`, an editor's save) breaks it where `write_text` through it does not. `deploy/skills.py::_fingerprint` branches on the link before the content.
