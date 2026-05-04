# The problem

AI coding agents ship as a conversational interface and a file tool. That's enough for a demo. It's not enough for a daily driver.

## What's missing out of the box

When you move from "occasionally ask Claude to explain a diff" to "pair with Claude for 8 hours a day across three projects", a collection of predictable problems emerge:

- **Session amnesia.** Each conversation starts from nothing. You re-explain the project, the conventions, the constraints, the person you are. You paste the same context every day.
- **No multi-context isolation.** One global `~/.claude/` directory mixes your personal experiments, your employer's private code, your client work, and your weekend side project. There is no way to switch cleanly.
- **No observability.** How much did last week cost? Which sessions actually changed the repo? Which tools were called? You can't answer any of these.
- **Knowledge is write-only.** You learn something in a session and it dies when the window closes. There is no loop back into future sessions.
- **Recurring jobs are yours to build.** Want a pre-compact summary? A weekly knowledge review? A nightly QMD re-index? You write the scheduler glue yourself, per platform.
- **No guardrails on tool use.** Out of the box the agent can `rm -rf`, `git reset --hard`, `terraform destroy`, or `cat .env` with no second-look. The blast radius of a bad turn is the blast radius of a shell. Per-profile policy belongs in front of every tool call.
- **Migration is all-or-nothing.** Adopting a new convention — moving knowledge, renaming profiles, splitting a setup — means editing many files by hand and praying.

Every one of these is solvable with enough shell scripts, cron entries, and discipline. That's what `lazy-harness` is: the shell scripts, the schedulers, and the discipline, packaged.

## Why a framework and not a set of dotfiles

The early versions of this codebase lived as a personal dotfiles-style repo. That worked for one user and one machine. It broke down at the seams:

- Every improvement was tangled with personal config. Sharing required untangling.
- There was no abstraction boundary between "the harness" and "the user's setup".
- Multi-agent portability was impossible. Every path assumed Claude Code.

Extracting `lazy-harness` as a generic framework made the boundary explicit: the framework knows about **profiles**, **hooks**, **knowledge**, **monitoring**, **scheduling** — agent-agnostic concepts. Personal config (the actual `CLAUDE.md`, the specific hook scripts you want) lives in `~/.config/lazy-harness/profiles/` and is versioned with your dotfiles, completely separate from the framework code.

## What `lazy-harness` is not

- It is not a Claude Code fork. It wraps Claude Code (and in the future other agents) without modifying them.
- It is not a chat wrapper. It never proxies your messages. It only manipulates the environment around the agent.
- It is not itself an MCP server, though it does orchestrate third-party MCP servers (QMD, Engram) into each profile's `settings.json` when those tools are installed. Its own integration with Claude Code is via settings, hooks, and the filesystem.
- It is not opinionated about your workflow. Every default is overridable; every feature is opt-in via `config.toml`.
