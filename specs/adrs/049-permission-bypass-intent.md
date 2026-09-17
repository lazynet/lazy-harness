# ADR-049: Permission bypass is a declared intent, not a forwarded flag

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-045 (the credential boundary), ADR-047 (`CopilotAdapter`), ADR-048 (Codex's rollout streams)

## Context

`lh run` resolves a profile, sets the agent's config-dir env var, and execs the
agent binary with **every remaining argument forwarded verbatim**. That
passthrough is the right default for almost everything a user types. It is the
wrong default for exactly one class of argument, and the alias that proves it is
the most-used entry point into the harness:

```
alias lcca="lh run --allow-dangerously-skip-permissions"
```

`--allow-dangerously-skip-permissions` is a Claude Code flag. `lh run` ships it
to whatever binary the resolved profile names. On a Codex profile it reaches a
parser that has never heard of it; on a Copilot profile the same. The alias is
not wrong about what the user wants — it is wrong about who is listening.

The axis also has **three positions rather than one**, and they are not
interchangeable. Claude Code distinguishes making bypass *available*
(`--allow-dangerously-skip-permissions`, documented as "Enable bypassing all
permission checks as an option, without it being enabled by default") from
turning it *on* (`--dangerously-skip-permissions`). Codex distinguishes
answering approvals without a human from removing the OS sandbox. A single flag
covering all of it would have to pick one meaning, and every collapse available
resolves in the **more permissive** direction.

## Decision

### 1. Three declared positions, on the adapter

```python
class Bypass(StrEnum):
    ENABLE = "enable"          # make bypass available; do not turn it on
    ACTIVATE = "activate"      # turn it on
    NO_SANDBOX = "no_sandbox"  # also remove the sandbox, where one exists

def bypass_argv(self, level: Bypass) -> list[str] | None:
    """Flags for this level, or None if this agent has no such level."""
```

`lh run --bypass=enable|activate|no-sandbox` expands one of them through the
resolved profile's adapter. The levels are ordered by how much they give away,
which is the property every rule below depends on.

### 2. `None` is an answer, and the answer is an error

An adapter that lacks a position returns `None`, and `bypass_argv_or_raise`
turns that into a `BypassUnsupportedError` carrying `agent` and `level` as
attributes. `lh run` exits 1 and names both. **Nothing is forwarded.**

The alternative — answering a missing level with the nearest one the agent does
have — is unacceptable in one specific direction. Every substitution available
is a larger grant than the one requested: answering `no-sandbox` with the
`activate` flag stops the prompts instead of removing the sandbox, and answering
`enable` with the `activate` flag turns on what the user asked only to have
available. An agent with no sandbox has no `NO_SANDBOX`; that is a reported
state, never a silent alias.

The error is structured rather than a string because the CLI renders the
message: a caller that had to parse prose to learn which level was refused
would re-derive what the raiser already knew. The refusal path is exercised
through the shipped `NullAdapter` sentinel and asserted on those attributes.

### 3. Everything else stays a passthrough

`--bypass` interprets one argument. The expansion is inserted after `argv[0]`
and before the user's own arguments, and nothing else is rewritten. This is
deliberately one axis and not a general argv translation layer: it is the only
forwarded flag whose misinterpretation is a safety property rather than a
usability one, and a general translator would be the "unified model that lies
in every direction" the parent design rejected for permissions.

`argv[0]` stays the adapter's `process_name()` — `claude`, `codex` — because
herdr identifies the agent from the process name. The dry-run tests parse the
argv back and assert `argv[0]` equals the name exactly, rather than substring
matching: `"codex" in output` is equally true of a binary path ending in
`/codex`.

### 4. Claude Code — two positions, evidence `[help]`

| Level | Flags |
|---|---|
| `ENABLE` | `--allow-dangerously-skip-permissions` |
| `ACTIVATE` | `--dangerously-skip-permissions` |
| `NO_SANDBOX` | `None` |

ENABLE is the flag `lcca` ships today, and the help text is why it is ENABLE
and not ACTIVATE: "as an option, without it being enabled by default". The
migration preserves the alias's semantics exactly, which is the point of
migrating it rather than redefining it.

`NO_SANDBOX` is `None` because Claude Code exposes no OS-sandbox switch on its
argv at all. The sandboxing it has is a property of where it is run.

### 5. Codex — two positions, evidence `[run]`

Measured against `codex-cli 0.154.0` by
`specs/gates/probes/codex-bypass-probe.sh`; the per-candidate rows are
`specs/designs/codex-evidence.md` §7.

| Level | Flags |
|---|---|
| `ENABLE` | `None` |
| `ACTIVATE` | `--approve-for-me` |
| `NO_SANDBOX` | `--dangerously-bypass-approvals-and-sandbox` |

Each candidate was asked to write a marker to **two** targets outside the
workspace — one under `$HOME`, one under a temp directory. Two rather than one
because the macOS Seatbelt policy permits temp writes under `workspace-write`:
scored on the temp target alone, `--approve-for-me` would have read as a full
bypass while the sandbox was still holding. That distinction is the entire
basis of the ACTIVATE row.

**ENABLE is `None`, and that is a measurement.** `baseline` and `-c
approval_policy="never"` were indistinguishable — neither ran a command at all
— and `--approve-for-me` ran one. Nothing on this version does what Claude
Code's ENABLE flag does, which is to change nothing about the current turn while
making the toggle reachable inside it. `--approve-for-me` was considered for
ENABLE and rejected on exactly this: it changed the outcome of the turn, so it
is already on.

**ACTIVATE is `--approve-for-me`**: the command ran unattended
(`wrote_outside_tmp=yes`) and the sandbox still refused the write outside the
workspace (`wrote_outside_home=no`). That is the definition of the position.
Named precisely, it routes approvals through an automatic review — "answered
without you", not "always granted".

**NO_SANDBOX is the combined flag**, documented as "Skip all confirmation
prompts and execute commands without sandboxing" — both halves, which is what
"also remove the sandbox" asks for. `-s danger-full-access` alone also reached
the `$HOME` target and is deliberately **not** the mapping: it strips the
sandbox while leaving the approval policy at its default, so on the interactive
launch `lh run` actually performs it would remove the sandbox and still prompt.

ACTIVATE and NO_SANDBOX do **not** collapse on this agent. Both are populated,
both are distinct flags, and neither is an alias for the other.

Two limits on the evidence, recorded rather than smoothed over:

- The probe drives `codex exec`, because that is what can be measured
  non-interactively, while `lh run` execs the top-level `codex`. Both mapped
  flags are present on both commands, so the transfer is `[help]` even though
  the behaviour is `[run]`.
- `-a/--ask-for-approval` is **top-level only**. `codex exec` refuses it with
  `error: unexpected argument '-a' found` (`[run]`), which is why it appears in
  no row. `--full-auto` does not exist on this version at either level.

### 6. `--dangerously-bypass-hook-trust` is a different axis and is never emitted

It sits on the same Codex help page and is tempting to sweep in. It governs
whether **hooks** run without persisted trust — this harness's own guardrails —
not whether the model needs approval for a tool call. Emitting it from
`--bypass` would disable the harness as a side effect of a request about the
agent. A test asserts no level on `CodexAdapter` returns it.

### 7. Copilot — no position, evidence: none

All three levels return `None`. ADR-047 ships only rows a `run` or a `log`
backed, and no probe has measured a permission-bypass flag on Copilot CLI.
Reading one off a help page and putting it in front of a binary whose argument
parsing this repo has never exercised is the practice that ADR's evidence
discipline exists to prevent. The probe rows that would change this are in
`specs/designs/copilot-evidence.md`.

## Consequences

- `lcca` becomes `alias lcca="lh run --bypass=enable"`. Semantics are preserved
  exactly on a Claude profile, and on a Codex or Copilot profile the alias now
  **fails loudly** where it previously forwarded a flag the binary did not know.
  That is the intended behaviour change and the reason the migration is worth
  making. The alias lands after the binary-first deploy, not with this change.
- A fourth position cannot be typed on the CLI without being declared on the
  enum first: the `click.Choice` is built from `Bypass`.
- Adding an agent means answering three questions about it, and `None` is a
  legitimate answer to all three. The `AgentAdapter` Protocol is
  `runtime_checkable`, so a new adapter that omits `bypass_argv` fails
  conformance rather than inheriting a default.
- `lh exec` is untouched. It was grepped for `dangerously` and forwards no
  bypass flag, so there is no second path to keep in step.
- Codex's ENABLE row is the one most likely to change. If a later version adds
  an available-but-off position, this ADR is superseded rather than edited.

## Alternatives considered

**A single `--yolo` flag.** The previous revision of the parent design proposed
it; it is withdrawn. It collapses three positions into one, and the direction it
collapses them in is more permissive — the user who wanted bypass *available*
gets it turned on, and the user who wanted it turned on loses the sandbox.

**Leaving `lcca` as-is and documenting that it is Claude-only.** The alias is
the single most-used entry point into the harness. "This alias is unsafe on some
profiles" is a footnote nobody reads at the moment it matters, and the moment it
matters is a launch that already happened.

**Answering a missing level with the neighbouring flag.** Rejected in §2. Every
available substitution is a larger grant than the one requested.

**Mapping Codex's ENABLE to `--approve-for-me`.** Rejected on the probe: it ran
the command, so it is not "available but off". Mapping it there would have made
`--bypass=enable` mean "off" on one agent and "on" on another.

**Mapping Codex's NO_SANDBOX to `-s danger-full-access`.** It is the cheaper
flag and it did reach the `$HOME` target. Rejected because it leaves the
approval policy at its default: on the interactive launch `lh run` performs, it
would remove the sandbox and still prompt, which is not what the level means.
