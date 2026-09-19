# Portable assets

A profile is a pile of content — instructions, skills, commands, subagent
definitions, settings. When that profile can run under more than one agent, each
piece has to answer a question it never had to answer before: **does this travel,
and if so, into what shape?**

The answers are not uniform, and pretending they were is how you ship a skill
your second agent cannot see.

| Asset | Travels? | How |
|---|---|---|
| System doc (`CLAUDE.md` / `AGENTS.md` / …) | ✅ | Assembled per agent from shared segments |
| Skills | ✅ | Projected into each agent's native skill root |
| Slash commands | ❌ | Native, per agent |
| Subagent definitions | ❌ | Native, per agent |
| Agent config documents | ❌ | Each adapter owns its own |
| MCP servers | partly | Only where the adapter exposes a target |

## One document, assembled per agent

Different agents load differently-named instruction files. Rather than keeping
a copy per agent and letting them drift, a profile keeps **segments** and the
harness assembles a document per destination:

```
~/.config/lazy-harness/profiles/personal/
├── head.md              # this profile's own opening
├── _common/
│   ├── common.md        # shared across profiles
│   └── claude-code.md   # agent-specific, optional
└── tail.md              # this profile's own closing
```

`head + common + <agent> + tail` renders to whichever destinations the adapter
names — `CLAUDE.md` for Claude Code, `AGENTS.md` for Codex,
`copilot-instructions.md` for Copilot. Every destination receives the identical
rendered bytes and is separately version-stamped.

Two details matter in practice:

- `system_docs()` returns a **list of destinations the agent loads**, not one
  recognised filename. A nested or multi-file target is expressible; an entry is
  a claim that the agent loads it.
- The assembled document is a **generated artifact**. It carries a `GENERATED
  by` header and does not belong in your dotfiles source — only the segments do.

`post-tool-use-sync-system-doc` regenerates the document when a segment changes,
resolving the adapter from `--profile` rather than the global agent. Before that
fix, editing a segment on a machine with mixed profiles regenerated the *wrong*
agent's contract file and left the right one stale.

Design:
[ADR-043](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/043-system-docs-by-role.md)
and [ADR-055](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/055-segment-rename-and-the-agent-segment.md).

## Three layers per profile

Profile content deploys in three layers, in ascending precedence:

```
profiles/personal/
├── CLAUDE.md, head.md, tail.md   # root — deployed to every agent
├── shared/
│   ├── skills/
│   └── commands/                 # shared — deployed to every agent
├── claude-code/
│   └── settings.json             # agent — only when this profile runs Claude Code
└── codex/
    └── hooks.json                # agent — only when this profile runs Codex
```

The agent directory names come from the registry, never from a list typed into
the deployer, so a new adapter brings its directory name with it.

Linking is per **file** rather than per directory when a name exists in more
than one layer, so `shared/skills/` and `codex/skills/` merge instead of one
shadowing the other. When the same name collides, the higher layer wins and the
deploy prints a line saying so.

`lh deploy` records the links it created in
`<config_dir>/.lazy-harness/links.json`. A first run without a ledger adopts
every existing symlink that resolves inside the profile source, so an existing
install is not orphaned. `lh profile migrate <name> [--dry-run]` moves an
unmigrated profile's root assets into the right layer, using each adapter's
`config_targets()` as the oracle. Migrating is optional — an unmigrated profile
still deploys its root to every agent — and running it twice is a no-op.

Mechanics in full: [how profiles and deploy work](../how/profiles-and-deploy.md).
Design: [ADR-052](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/052-profile-assets-per-agent.md).

## Skills travel; commands and subagents do not

Skills are the one asset class projected across agents. `lh deploy` resolves
`shared/skills/` plus `<agent>/skills/` with the layer precedence above, then
links each skill into the agent's **native** root:

| Agent | Skill root | Scope |
|---|---|---|
| Claude Code | `<config_dir>/skills` | Per profile |
| Codex | `~/.agents/skills` | **Global across profiles** |
| Copilot | — | No measured discovery root |

Codex's root being global is the sharp edge. Two profiles claiming the same
global skill name with different content is refused **before the first write** —
the whole plan, not the colliding file — because a partial apply would leave the
host catalog in a state neither profile described. A separate ownership ledger
at `<config_dir>/.lazy-harness/skill-links.json` drives cleanup. Codex can also
opt out of host discovery entirely via `skip_host_skill_discovery` in its
`config.toml`, and the adapter then reports no root rather than asserting one.

Slash commands and subagent definitions stay **native**. They are not projected,
not translated, and not warned about — they are simply each agent's own.

Design: [ADR-059](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/059-portable-skills-native-commands-agents.md).

## `AGENTS.md` is the repository contract

Everything above is about *your profile*. A **repository's** own rules are a
separate contract, and there the answer is a single file: `AGENTS.md`.

`CLAUDE.md` is rejected as canonical for a measured reason — on Claude Code
2.1.278 a `CLAUDE.md` shadows direct parent-chain `AGENTS.md` discovery, and
imports inside a parent `CLAUDE.md` are not expanded. Agent-specific guidance
goes in a labelled section *inside* `AGENTS.md`, so a root session and a nested
one receive the same contract under either agent.

```bash
lh repo instructions            # the current repository
lh repo instructions ../other   # any path
```

Two findings, each naming the file to change:

| Code | Meaning |
|---|---|
| `missing-agents-md` | No root `AGENTS.md`, so repository rules are not portable |
| `claude-md-shadows-agents` | A `CLAUDE.md` blocks parent-chain `AGENTS.md` discovery |

Exit 0 when clean, 1 with one line per finding — so it works as a CI step, not
only a local convenience.

Design: [ADR-060](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/060-agents-md-is-the-portable-repository-contract.md).
