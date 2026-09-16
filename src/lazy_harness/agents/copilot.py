"""Copilot CLI adapter — the half `copilot 1.0.83` was seen to do, and no more.

This adapter ships **before** its probes, which inverts the repo's own gate for
an adapter over an external binary. That is deliberate and it is the whole
shape of the file: everything here is pinned to a line the multi-agent design
records as `run` (the binary was driven and its behaviour read) or `log`
(observed in a session log on this machine). Every other row — a string in the
vendor artifact, a type in the shipped SDK, a page of vendor documentation — is
a **probe** in `specs/designs/copilot-evidence.md`, and this file declares
nothing for it. ADR-047 records the trade and lists what goes inert meanwhile.

The two gaps that are decisions rather than oversights:

**No tool maps to `MODIFY_FILE`.** Copilot has never been observed editing a
file — not in a run, not in a session log. `apply_patch` and
`str_replace_editor` occur as strings in `prebuilds/darwin-arm64/runtime.node`,
which per the design's first gate establishes that the names exist and nothing
about whether either is the tool. So every edit-gating builtin is inert here,
and that is a measured absence rather than a missing mapping.

**`additionalContext` is not emitted.** It is named in the 1.0.40 bundle and
declared on four of the SDK's output types, both `src`-level; no run has shown
the declarative hook path reading it. Emitting it would hand every
context-injecting builtin a channel nothing has shown Copilot reads — the same
reason `CodexAdapter` emits no `systemMessage`. Probe 2 closes it.

`TranscriptReader` is **step 12's**, and the design pins the method: Copilot's
reader is *generated* from `schemas/session-events.schema.json`, shipped beside
the binary in the extracted package tree, rather than reverse-engineered from
event samples. `HeadlessAgent` is unclaimed for `CodexAdapter`'s reason —
`copilot -p` is known to start a run, and nothing here has parsed its output.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lazy_harness.agents.base import (
    ConfigArtifact,
    HookDecision,
    HookEntry,
    HookEvent,
    HookOutput,
    HookSupport,
    Operation,
    ToolCall,
    Verdict,
    WriteOp,
)
from lazy_harness.core.paths import expand_path

# The eleven event names 1.0.83 accepts, established **by rejection**: sixteen
# candidates were written into a hook file and the binary read back for which it
# dropped ([run], 1.0.83). It is a named constant for the reason Codex's is —
# the failure is silent-adjacent. An unrecognised name is dropped at load behind
# a single `Ignoring unknown hook event(s) in <file>: …` line covering all of
# them at once, so one mis-cased name disappears into a message that reads like
# it is about a different one.
#
# This supersedes the twelve-name list read off the 1.0.40 bundle with `strings`,
# which survived three revisions of the design because each one cited the last.
COPILOT_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "preToolUse",
        "postToolUse",
        "postToolUseFailure",
        "preMcpToolCall",
        "permissionRequest",
        "sessionStart",
        "sessionEnd",
        "preCompact",
        "notification",
        "subagentStart",
        "subagentStop",
    }
)

# The five the same run watched the binary drop. Kept beside the accepted set
# rather than left implicit in its complement, because this is where the
# camelCase near-misses live: `userPromptSubmit` differs from a real event name
# by nothing a reader would notice, and `stop` is the event three of this
# repo's builtins are written against.
COPILOT_REJECTED_EVENT_NAMES: frozenset[str] = frozenset(
    {"userPromptSubmit", "postCompact", "stop", "error", "preResponse"}
)

# Canonical event name -> how Copilot delivers it.
#
# `session_stop`, `post_compact` and `user_prompt_submit` are **absent keys**,
# which the contract reads as "not delivered at all" — a stronger statement than
# an event that fires and honours nothing. That distinction is what lets
# `lh doctor` tell a missing installation from a missing signal: `stop_verify_guard`
# on Codex installs, runs and finds no goal marker; on Copilot nothing installs,
# because `stop` never survives config load.
#
# Four canonical names are new here — `post_tool_use_failure`, `pre_mcp_tool_call`,
# `subagent_start`, `subagent_stop`. No builtin declares them today, so they
# deploy nothing; they exist because `hook_events()` is the only mapping, and an
# accepted event left out of it is unreachable forever.
#
# `verdicts` carries `DENY` on one event and nothing anywhere else. The deny was
# measured against a control with four envelopes varied ([run], 1.0.83); `allow`
# and `ask` appear in the SDK's output union and have **never been observed
# being honoured**, and `BLOCK` has no home at all — `agentStop`, whose SDK
# output is the only one declaring `decision: "block"`, is not one of the eleven.
_HOOK_EVENTS: dict[str, HookSupport] = {
    "pre_tool_use": HookSupport("preToolUse", frozenset({Verdict.DENY})),
    "post_tool_use": HookSupport("postToolUse"),
    "post_tool_use_failure": HookSupport("postToolUseFailure"),
    "pre_mcp_tool_call": HookSupport("preMcpToolCall"),
    "permission_request": HookSupport("permissionRequest"),
    "session_start": HookSupport("sessionStart"),
    "session_end": HookSupport("sessionEnd"),
    "pre_compact": HookSupport("preCompact"),
    "notification": HookSupport("notification"),
    "subagent_start": HookSupport("subagentStart"),
    "subagent_stop": HookSupport("subagentStop"),
}

# Every tool name a real 1.0.83 session was seen to call ([log], 1.0.83):
# `bash` (28 calls), `view` (27), `web_fetch` (24), `rg` (7), `web_search` (3),
# `task`, `skill`, `glob`. Lowercase, and **unnormalised** — Codex rewrites
# `exec_command` to `Bash` before the payload is written and Copilot does not,
# so a Claude-shaped name or matcher here installs something that never fires.
COPILOT_TOOL_NAMES: frozenset[str] = frozenset(
    {"bash", "view", "rg", "glob", "task", "skill", "web_fetch", "web_search"}
)

# Two mappings, and the second is honest about being half a mapping.
#
# `bash` is complete: `toolArgs` is `{"command": …, "description": …}`, a nested
# JSON object rather than the JSON-encoded string the documentation claimed
# ([run], 1.0.83), so `ToolCall.command` carries real shell text and
# `pre_tool_use_security`'s command denylist is live on Copilot.
#
# `view` maps the operation and fills nothing. Its argument key has never been
# measured — no run, no log, no SDK type names it — so `reads` stays `()` and
# `pre_tool_use_read_size` deploys, runs, exits 0 and guards nothing. That is
# the F8 gate's own finding restated: a mapping without a structure revives
# nothing. It is mapped anyway because the operation is not in doubt and the
# gate that reports coverage reads `operation`; the missing half is named in
# ADR-047 and closed by probe 1.
#
# There is deliberately no `MODIFY_FILE` entry. See the module docstring.
_TOOL_OPERATIONS: dict[str, Operation] = {
    "bash": Operation.RUN_COMMAND,
    "view": Operation.READ_FILE,
}

# The one file the harness owns, and why it is a path and not a stamp.
#
# Copilot loads `$COPILOT_HOME/hooks/*.json` — a glob ([run], 1.0.83: registered
# and fired). So ownership can be the **filename**: the harness writes this path
# and nothing else, the user's own hooks live in sibling files under the same
# glob, and a retirement keys on the path rather than on a marker parsed out of
# the document. `CodexAdapter` needs a `description` stamp because Codex loads
# one fixed `hooks.json` shared with the user; Copilot's glob removes the
# problem instead of solving it — which matters here because whether this
# document tolerates an unknown top-level key at all is unmeasured
# (`specs/designs/copilot-evidence.md` §4).
HOOKS_FILE = "hooks/lazy-harness.json"

# `version: Required` and `version: Invalid literal value, expected 1` are both
# in the string region belonging to `src/runtime/src/hooks/declarative.rs`
# ([src], 1.0.83). This is the one shape the adapter writes and cannot verify,
# and phase 0 of `specs/gates/probes/copilot-probe1.sh` exists to fail it loudly
# rather than leave a deploy writing a document Copilot ignores in silence.
CONFIG_VERSION = 1


class CopilotAdapter:
    """Copilot CLI — the full `AgentAdapter` and `ConfigPlanner` surface."""

    @property
    def name(self) -> str:
        return "copilot"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        """`COPILOT_HOME`, honoured end to end ([run], 1.0.83)."""
        return "COPILOT_HOME"

    def resolve_binary(self) -> Path | None:
        found = shutil.which("copilot")
        return Path(found) if found else None

    def supported_hooks(self) -> list[str]:
        return list(_HOOK_EVENTS)

    def hook_events(self) -> dict[str, HookSupport]:
        return dict(_HOOK_EVENTS)

    # --- the canonical hook contract (ADR-041) ---

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        """camelCase, and only the keys a run was seen to deliver.

        The observed `preToolUse` payload is `{sessionId, timestamp, cwd,
        toolName, toolArgs}` ([run], 1.0.83) — and what is *missing* from it is
        as load-bearing as what is there:

        `hook_event_name` has no counterpart under any spelling, so `event`
        comes from the caller. The runner knows which event it was invoked for;
        the payload never says.

        `transcript_path` is absent too, which is the asymmetry decision 11 and
        step 12 lean on. Codex hands the path over outright, so a reader can be
        driven straight from the hook; a Copilot reader will need
        `locate_sessions` and the session directory.

        `workingDirectory` is **not** read as a fallback for `cwd`, although the
        SDK's `BaseHookInput` names it. The wire said `cwd`; the SDK is `src`,
        and a fallback would encode a `src` row as behaviour — which is the one
        thing this adapter is built not to do. The discrepancy is probe 1.

        The string fields go through `isinstance` for Claude Code's reason:
        `str()` on a list yields something that looks like a session id and is
        not one, and this field keys the metrics, the memory scope and the
        transcript reads.
        """
        session = payload.get("sessionId")
        cwd = payload.get("cwd")
        return HookEvent(
            event=event,
            profile=profile,
            session_id=session if isinstance(session, str) else "",
            cwd=Path(cwd) if isinstance(cwd, str) else Path(),
            transcript_path=None,
            tool=self._parse_tool(payload),
            raw=payload,
        )

    @staticmethod
    def _parse_tool(payload: dict) -> ToolCall | None:
        """`toolName` / `toolArgs`, with the argument mapping the adapter owns.

        Copilot does not normalise its tool names to Claude Code's, and it was
        never claimed to normalise the argument *fields* — which was always the
        half that mattered. A tool absent from `_TOOL_OPERATIONS` still yields a
        `ToolCall` with its native name and `operation=None`: "this ran and no
        builtin guards it", never "this is harmless".
        """
        name = payload.get("toolName")
        if not isinstance(name, str) or not name:
            return None
        arguments = payload.get("toolArgs")
        arguments = arguments if isinstance(arguments, dict) else {}
        command = arguments.get("command")
        return ToolCall(
            native_name=name,
            operation=_TOOL_OPERATIONS.get(name),
            command=command if isinstance(command, str) else None,
            raw_input=arguments,
        )

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        """Top level and unwrapped, on stdout, exit 0.

        Measured against a control with four envelopes varied and only the
        hook's stdout changing ([run], 1.0.83): this shape produced
        `✗ … Denied by preToolUse hook: <reason>` and the command's marker never
        appeared, while `hookSpecificOutput`, Claude Code's legacy
        `{"decision":"block"}` and `{"continue":false}` were each read, logged as
        `[hook stdout]` text, and ignored. The reason string comes back in the
        refusal verbatim, which is what proves the JSON was parsed as a verdict
        rather than failing closed on a parse error.

        Exit 2 with the reason on stderr is Copilot's second route and is not
        taken. One refusal channel is emitted — the one whose text Copilot was
        seen to echo back — because two channels for one decision is two things
        to keep true.

        Nothing else is emitted at all. `additionalContext`, `systemMessage` and
        `suppressOutput` are `src`-level names with no observed reader on this
        path, and a key the agent ignores is a channel a builtin believes it
        has. What that costs is named in ADR-047 rather than hidden here.
        """
        support = _HOOK_EVENTS.get(event.event)
        verdict = decision.verdict
        if verdict is not None and (support is None or verdict not in support.verdicts):
            honoured = sorted(v.value for v in support.verdicts) if support else []
            raise ValueError(
                f"copilot does not honour {verdict.value!r} on {event.event!r}; "
                f"honoured here: {honoured}"
            )
        if verdict is not Verdict.DENY:
            return HookOutput(stdout=None, stderr="", exit_code=0)
        body = {
            "permissionDecision": verdict.value,
            "permissionDecisionReason": decision.reason,
        }
        return HookOutput(stdout=json.dumps(body) + "\n", stderr="", exit_code=0)

    # --- config documents (ConfigPlanner) ---

    def config_targets(self) -> list[Path]:
        """One file. MCP is deliberately not a target — see `plan_config`."""
        return [Path(HOOKS_FILE)]

    def plan_config(
        self,
        hooks: dict[str, list[HookEntry]],
        servers: dict[str, dict],
        existing: dict[Path, str],
        *,
        binary: str | None = None,
    ) -> list[WriteOp]:
        """One document, replaced wholesale, and no MCP write at all.

        `servers` is **ignored**, which is a decision with a cost and it is
        recorded in ADR-047 rather than swallowed. `~/.copilot/mcp-config.json`
        is marked `present on disk` in the design and the 2026-09-14 sweep left
        it there on purpose: *a path that exists is not a path the binary was
        seen to read*. It is also a file Copilot writes itself, beside
        `permissions-config.json`, whose `locations.<abs path>.tool_approvals[]`
        is every permission the user has granted and is not reconstructible. A
        write there is the one the design's own config table warns against.

        `existing` is read only to decide whether a retirement is owed, and
        `binary` is ignored: the commands arrive already built, and the document
        has no free slot to stamp a launcher into.
        """
        groups = self._hook_groups(hooks)
        target = Path(HOOKS_FILE)
        if not groups:
            # A file the harness wrote and no longer generates is retired; one
            # it never wrote is left alone. The distinction is free here because
            # the path is the harness's own — under Copilot's `hooks/*.json`
            # glob a user's file is a sibling, never this one.
            if target in existing:
                return [WriteOp(artifact=None, relative_path=target)]
            return []
        document = {"version": CONFIG_VERSION, "hooks": groups}
        return [
            WriteOp(
                artifact=ConfigArtifact(
                    relative_path=target,
                    content=json.dumps(document, indent=2) + "\n",
                ),
                relative_path=target,
            )
        ]

    @staticmethod
    def _hook_groups(hooks: dict[str, list[HookEntry]]) -> dict[str, list[dict]]:
        """Canonical events -> `{nativeName: [entry, ...]}`.

        An event Copilot does not deliver is dropped here rather than written
        and rejected at load, and the difference is the whole profile: an
        unrecognised name does not fail alone, it is collected into one
        `Ignoring unknown hook event(s)` line — so one unsupported event
        configured by hand can take every other hook in the file down with it.

        `matcher` is omitted when absent rather than written empty. `matcher
        cannot be empty` is a load error in the runtime's own strings, making
        the empty string the one value guaranteed to drop the hook. Whether an
        omitted matcher fires on every call, as it does on Codex, is probe 4.
        """
        groups: dict[str, list[dict]] = {}
        for event, entries in hooks.items():
            support = _HOOK_EVENTS.get(event)
            if support is None or not entries:
                continue
            groups[support.native_name] = [
                {
                    **({"matcher": entry.matcher} if entry.matcher else {}),
                    "command": entry.command,
                }
                for entry in entries
            ]
        return groups

    # --- the rest of the adapter surface ---

    def global_config_link(self) -> Path | None:
        """None — `~/.copilot` is the vendor's directory, not the harness's.

        `deploy/symlinks.py:16-21` renames an existing target to `<name>.bak`
        before linking, and this one is not an empty mount point: it holds
        `permissions-config.json`, which Copilot writes as the user approves
        things, plus `settings.json`, `mcp-config.json` and `session-store.db`.
        None of that is reconstructible. Claude Code can link `~/.claude`
        because the harness owns what is under it.
        """
        return None

    def mcp_config_file(self) -> str:
        """Empty — this adapter places no MCP config. See `plan_config`."""
        return ""

    def session_dirs(self) -> dict[str, str]:
        """`session-state/<uuid>/events.jsonl` ([log], 1.0.83), self-identifying
        `"producer": "copilot-agent", "copilotVersion": "1.0.83"`.

        `logs` stays empty although `~/.copilot/logs/` exists on disk: a
        directory that exists is not a directory the binary was seen to write,
        and naming it would put a path in front of a reader that may be stale.
        """
        return {"sessions": "session-state", "logs": "", "queue": ""}

    def credentials_file(self) -> str | None:
        """None, and here the negative was **measured** rather than inferred.

        Every deny-matrix run used a throwaway `COPILOT_HOME` and auth survived
        it ([run], 1.0.83) — so the credential is not under the config dir at
        all. That is exactly what ADR-045 reserves `None` for: not "the file is
        missing" and not "the shape is unparsed", but "the harness cannot speak
        for this agent's login". `CodexAdapter` answers `None` on the weaker
        ground of a file nobody opened; this one answers it on a run.
        """
        return None

    def system_docs(self) -> list[Path]:
        """One destination, and it is the first that is not a repo filename.

        `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md`
        are **repository-discovered** by Copilot — recognised inside a repo,
        never loaded from a config dir. Writing one here installs nothing, which
        is the distinction ADR-043 exists to make.

        `instructions/**/*.instructions.md` is the second claimed user-level
        destination and is **not** returned. It is a glob rather than a path,
        and `system_docs()` asserts the agent loads every entry it returns —
        each receiving the identical rendered bytes. Two entries would be a
        claim about stacking that nothing has measured; probe 6 settles it.
        """
        return [Path("copilot-instructions.md")]

    def process_name(self) -> str:
        return "copilot"
