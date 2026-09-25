# Supported agents

`lazy-harness` wraps more than one coding agent. A profile names the agent it
runs, and every layer below — hooks, deploy, launch, metering, skills — resolves
that agent **per profile**, not once per machine. Two profiles on the same
laptop can run different agents, share a root directory, and both stay correct.

```toml
[profiles.personal]
config_dir = "~/.claude-personal"       # agent omitted: inherits [agent].type
roots = ["~/code/personal"]

[profiles.cx]
agent = "codex"
config_dir = "~/.codex-cx"
roots = ["~/code/experiments"]
```

The registry holds four adapters: `claude-code`, `codex`, `copilot` and `null`
(a test sentinel that honours nothing). An unregistered name is refused loudly
at load time rather than silently falling back.

## What "supported" means here

Support is not a boolean, and this page does not pretend it is. An adapter
encodes **what a run or a log measured**, never what a vendor's help page
claims. That gives three honest states, and the tables below use all three:

| State | Meaning |
|---|---|
| ✅ | Measured against a real binary and encoded. |
| ❌ | Measured and absent — the agent has no such thing. |
| — | Not measured. No probe has run, so nothing is asserted. |

The distinction is load-bearing. `CopilotAdapter.bypass_argv()` returns `None`
for all three bypass levels not because Copilot lacks them but because nobody
has measured them, and putting an unmeasured flag in front of a binary is how
you hand an agent a permission grant you did not intend.

## Capability matrix

Identification and launch:

| | Claude Code | Codex | Copilot |
|---|---|---|---|
| `config.toml` value | `claude-code` | `codex` | `copilot` |
| Config-dir env var | `CLAUDE_CONFIG_DIR` | `CODEX_HOME` | `COPILOT_HOME` |
| Binary | `claude` | `codex` | `copilot` |
| Default config dir | `~/.claude-<profile>` | `~/.codex-<profile>` | `~/.copilot-<profile>` |
| `~/.claude`-style global link | ❌ | ❌ | ❌ |

What the harness writes into the config dir:

| | Claude Code | Codex | Copilot |
|---|---|---|---|
| System doc | `CLAUDE.md` | `AGENTS.md` | `copilot-instructions.md` |
| Config documents | `settings.json`, `.claude.json` | `hooks.json`, `config.toml` | `hooks/lazy-harness.json` |
| MCP servers placed | ✅ `.claude.json` | ✅ merged into `config.toml` | ❌ no MCP document |
| Skill root | `<config_dir>/skills` | `~/.agents/skills` (host catalog) | — |

What the harness can read back out:

| | Claude Code | Codex | Copilot |
|---|---|---|---|
| Sessions directory | `projects/` | `sessions/` | `session-state/` |
| Transcript reader (metering) | ✅ | ✅ | — |
| Session/project identity | ✅ | ✅ | — |
| Credentials file the harness may check | `.credentials.json` | ❌ | ❌ (measured: auth survives a throwaway `COPILOT_HOME`) |
| Headless `lh exec` | ✅ | ❌ | ❌ |

Permission bypass — `lh run --bypass=<level>`:

| Level | Claude Code | Codex | Copilot |
|---|---|---|---|
| `enable` | `--allow-dangerously-skip-permissions` | ❌ | — |
| `activate` | `--dangerously-skip-permissions` | `--approve-for-me` | — |
| `no-sandbox` | ❌ | `--dangerously-bypass-approvals-and-sandbox` | — |

An unsupported level is an error naming the agent and the level; nothing is
forwarded. It is never answered with a neighbouring level, because the levels
are ordered by how much they give away. Full reasoning: [`lh run
--bypass`](../reference/cli.md#-bypass-permission-bypass-as-a-declared-intent)
and [ADR-049](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/049-permission-bypass-intent.md).

## A hook the agent cannot serve is left out, and named

Each built-in hook declares the `Signal`s it needs and the `Operation`s it
reasons about. Each adapter declares what its agent actually delivers. `lh
deploy` resolves the two before it writes a profile's config, omits every hook
the profile's agent cannot serve, and prints each omission:

```
· stop-verify-guard omitted in 'cx': agent 'codex' does not deliver goal_status
```

A built-in declared for other agents only is omitted the same way, with
`declared for agents <list>` as the reason.

This is not a deploy failure — the exit code is unchanged and other profiles are
untouched. `lh doctor` reads the same resolver, so what doctor reports is what
deploy omits. The mechanism, and why a silently-installed inert hook is worse
than an absent one, is in [the agent contract](contract.md).

## Picking an agent for a profile

```bash
lh profile add cx --config-dir ~/.codex-cx --roots ~/code/experiments
# then set agent = "codex" under [profiles.cx] in config.toml
lh deploy --profile cx
lh doctor
lh run --profile cx
```

`lh doctor` is the single place that answers "is this profile's agent wired
correctly?" — it reports shared roots and their defaults, hook signal and
operation gaps, transcript readability, MCP servers an adapter cannot place,
and Codex hook trust. `lh doctor --json` emits the same verdicts by key for a
CI gate.

## Per-agent notes

- [Codex](codex.md) — hook trust, two edit paths, rollout streams, `AGENTS.md`.
- [Copilot](copilot.md) — eleven measured events, deny-only verdicts, and the
  large unmeasured surface.
- Claude Code is the reference implementation; it is what every other page on
  this site shows by default.

## Design record

The contract is [ADR-041](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/041-multi-agent-hook-contract.md),
frozen on 2026-09-15 only after a second, non-identity adapter had run against
it. The design and its blast-radius document were accepted on 2026-09-18 on an
end-to-end acceptance run against the second agent — 17 assertions, none failed.

Adoption is measured, not assumed: a kill criterion opens on **2026-11-11** and
compares launches on a non-Claude profile against the trailing Claude baseline.
Below the threshold the adapters are removed rather than kept. `lh doctor`
prints `horizon opens 2026-11-11` until then. See [the roadmap](../roadmap.md),
Theme 5.
