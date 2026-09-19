# Copilot

The Copilot adapter is **partial, and deliberately so**. Every row in it was
confirmed by a real `copilot` run or a real log on **1.0.83**; nothing was read
off a bundle or a doc page. Where no probe has run, the adapter answers "no"
rather than guessing, and this page says which is which.

Use it when you want a Copilot profile deployed and reported alongside your
other agents. Do not expect the hooks that shape a Claude Code session to shape
a Copilot one.

```toml
[profiles.gh]
agent = "copilot"
config_dir = "~/.copilot-gh"
roots = ["~/code/scratch"]
```

## Hook events

Eleven event names are encoded. They are camelCase, and the list is what
survived trying sixteen candidates against the binary — the five that were
rejected are absent from the adapter rather than encoded hopefully:

`preToolUse`, `postToolUse`, `postToolUseFailure`, `preMcpToolCall`,
`permissionRequest`, `sessionStart`, `sessionEnd`, `preCompact`,
`notification`, `subagentStart`, `subagentStop`.

Three events the harness leans on **do not exist**: `stop`, `postCompact` and
`userPromptSubmit`. Every built-in that needs one of them installs nothing on a
Copilot profile — among them `stop-verify-guard`, `engram-persist` and
`session-export`. `lh deploy` names each omission as it writes the profile.

## What a hook can decide

One verdict, one shape: a top-level `{"permissionDecision": "deny",
"permissionDecisionReason": …}` with exit 0. Any other verdict raises rather
than being approximated.

`additionalContext` is **not emitted**. It is unverified on this binary, so
`context-inject` and every other context-injecting hook has no effect on a
Copilot session. This is the single largest practical gap.

## Tool operations

The tool map has two entries: `bash → run_command` and `view → read_file`.

There is **no** `modify_file` mapping, because no tool has been observed editing
a file. And `view`'s argument key was never measured, so a `ToolCall`'s `reads`
comes back empty — the mapping exists but is inert. `lh doctor`'s **Hook
operations** section reports both facts.

## What the harness writes

| Path | Note |
|---|---|
| `$COPILOT_HOME/hooks/lazy-harness.json` | Ownership is by filename, inside a glob directory |
| `$COPILOT_HOME/copilot-instructions.md` | The system doc destination |

`copilot-instructions.md` is the first destination that is not a *repository*
filename. `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and
`.github/copilot-instructions.md` are all discovered by Copilot **inside a
repo**, never loaded from a config dir — writing one there installs nothing,
which is exactly the distinction
[ADR-043](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/043-system-docs-by-role.md)
exists to make.

`instructions/**/*.instructions.md` is a second claimed destination and is
**not** returned. It is a glob, not a path, and `system_docs()` asserts the
agent loads every entry it returns. Two entries would be a claim about stacking
that nothing has measured.

**No MCP servers are placed.** `mcp_config_file()` is empty and `plan_config`
does not plan one. `lh doctor` surfaces this rather than hiding it — e.g.
`· copilot/mcp: 3 detected servers not placed — adapter exposes no MCP target`.

## What the harness cannot do yet

| Surface | State | Why |
|---|---|---|
| Metering | not implemented | No `TranscriptReader`. Transcripts exist at `session-state/<uuid>/events.jsonl` and are self-identifying, so `lh doctor`'s **Transcripts** section reports them as `unread` |
| `lh run --bypass` | error on all three levels | No probe has measured a bypass flag; inventing one from a help page would put an unmeasured permission grant in front of an unexercised argument parser |
| Skills | no root | No positive-and-negative discovery probe exists yet |
| Credentials | `n/a` | **Measured**: auth survived every throwaway `COPILOT_HOME`, so the credential is not under the config dir at all |
| Logs directory | not declared | `~/.copilot/logs/` exists on disk, but the binary was never seen writing it |

That last row is the adapter's discipline in miniature: a directory that exists
is not a directory the binary writes, and naming it would put a possibly-stale
path in front of a reader.

## Design record

[ADR-047](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/047-copilot-adapter.md)
records the adapter and the evidence rule behind it. The outstanding probes —
including the one that would settle the `system_docs` stacking question — are
listed in `specs/designs/copilot-evidence.md` and
`specs/gates/probes/copilot-probe1.sh`.
