"""Codex CLI adapter — the throwaway that runs step 4's contract gate.

Deliberately the smallest thing that can carry three builtins to a real Codex
session. The adapter step 9 ships is a different object; this one exists to make
the canonical hook contract fail where it is going to fail, while three hooks
depend on it instead of eighteen.

Everything here is pinned to behaviour **observed** against `codex-cli 0.154.0`
with `CODEX_HOME` pointed at a disposable directory. Where the binary was not
exercised, the adapter declares nothing rather than mirroring Claude Code: a
guess that reads as a capability is what the gate is supposed to catch.
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

# Every event name this Codex accepts, read off the binary's own string table.
#
# It is a named constant rather than an inline literal because of how Codex
# fails: an event name it does not recognise is dropped with **no diagnostic of
# any kind** — no warning, no `hook:` line, nothing fires. A mis-cased name is
# therefore indistinguishable at the console from a hook that is merely
# untrusted, and the only way to tell them apart is the interactive review
# screen. `test_every_emitted_native_name_is_one_codex_accepts` checks the
# mapping below against this set so the two cannot drift apart silently.
CODEX_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "Interrupt",
    }
)

# Canonical event name -> how Codex delivers it. The single place the native
# casing lives; `supported_hooks()` and `plan_config()` both read it.
#
# `verdicts` is gated on evidence, as it is for Claude Code, and here the
# evidence is unusually one-sided. `deny` was proved by effect: the file the
# model was told to create was never created, across four attempts, and Codex
# echoed the reason back verbatim. `allow` without `updatedInput` and `ask` are
# both rejected as an unsupported `permissionDecision`, and Codex then **fails
# open** and runs the tool — so declaring either would let deploy install a
# guard whose refusals are approvals. `Stop` is named by the binary but no
# verdict was ever observed being honoured there, which is why `session_stop`
# carries the empty set rather than Claude Code's `BLOCK`.
#
# `notification` is absent, not empty: Codex names no such event, and an absent
# key is the contract's way of saying "not delivered at all".
_HOOK_EVENTS: dict[str, HookSupport] = {
    "session_start": HookSupport("SessionStart"),
    "session_stop": HookSupport("Stop"),
    "session_end": HookSupport("SessionEnd"),
    "pre_compact": HookSupport("PreCompact"),
    "post_compact": HookSupport("PostCompact"),
    "pre_tool_use": HookSupport("PreToolUse", frozenset({Verdict.DENY})),
    "post_tool_use": HookSupport("PostToolUse"),
    "user_prompt_submit": HookSupport("UserPromptSubmit"),
    "permission_request": HookSupport("PermissionRequest"),
}

# Codex normalises its native tool name to Claude's on the hook wire: the model's
# own reasoning in the same transcript says it is calling `exec_command`, and the
# payload says `Bash`. Only the shell tool was exercised, so only the shell tool
# is mapped — a tool absent here parses with `operation=None`, which is "this
# ran, and no builtin has been written to guard it", not "this is harmless".
_TOOL_OPERATIONS: dict[str, Operation] = {"Bash": Operation.RUN_COMMAND}

# The file the harness owns, and the decision behind it.
#
# Codex loads hooks from `$CODEX_HOME/config.toml` *and* `$CODEX_HOME/hooks.json`,
# additively, and asks the deployer to pick one. The harness picks `hooks.json`
# because `config.toml` is not ours: Codex writes the `[hooks.state]` table of
# `trusted_hash` entries back into it, alongside `[projects.*]` trust levels, so a
# deploy that owns that file can silently revoke the user's own trust decisions.
# `hooks.json` holds nothing but hook declarations, which lets this adapter
# replace it wholesale instead of merging.
#
# **The choice is frozen at the first deploy.** The trust state key is
# `<absolute path of the declaring file>:<snake_case event>:<group index>:<handler
# index>` — path-scoped. The *hash* is stable across the two representations, but
# the key is not, so moving a hook from `hooks.json` to `config.toml` (or back)
# re-prompts for every hook even though nothing about the hook changed. Switching
# representation costs a full re-trust; it is not a refactor.
_HOOKS_FILE = "hooks.json"

# The only free-text slot the document has: the top level accepts `description`
# and `hooks` and nothing else — any other key is a parse error that drops every
# hook in the file behind one warning. It deliberately carries no version. The
# trust key is scoped to this file, so a stamp that churns per release rewrites
# the declaring file on every upgrade, and whether that disturbs the stored
# hashes was never measured. Nothing is gained by finding out: the harness owns
# the whole file, so it needs no marker to recognise its own entries.
_DESCRIPTION = "Managed by lazy-harness. Edits are overwritten on the next deploy."


class CodexAdapter:
    """Codex CLI, as much of it as step 4's gate needs."""

    @property
    def name(self) -> str:
        return "codex"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        return "CODEX_HOME"

    def resolve_binary(self) -> Path | None:
        found = shutil.which("codex")
        return Path(found) if found else None

    def supported_hooks(self) -> list[str]:
        return list(_HOOK_EVENTS)

    def hook_events(self) -> dict[str, HookSupport]:
        return dict(_HOOK_EVENTS)

    # --- the canonical hook contract (ADR-041) ---

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        """Codex's payload is Claude-shaped, and that is an observation, not an
        assumption: snake_case keys, `hook_event_name` carrying the PascalCase
        event name, `tool_name` / `tool_input` / `tool_use_id`.

        The three string fields are read with `isinstance` for Claude Code's
        reason — `str()` on a list yields something that looks like a session id
        and is not one, and these key the metrics, the memory scope and the
        transcript reads.
        """
        session = payload.get("session_id")
        cwd = payload.get("cwd")
        transcript = payload.get("transcript_path")
        declared = transcript if isinstance(transcript, str) and transcript else ""
        return HookEvent(
            event=event,
            profile=profile,
            session_id=session if isinstance(session, str) else "",
            cwd=Path(cwd) if isinstance(cwd, str) else Path(""),
            transcript_path=Path(declared) if declared else None,
            tool=self._parse_tool(payload),
            tool_use_id=payload.get("tool_use_id"),
            tool_response=payload.get("tool_response"),
            prompt=payload.get("prompt"),
            permission_mode=payload.get("permission_mode"),
            source=payload.get("source"),
            trigger=payload.get("trigger"),
            message=payload.get("message"),
            raw=payload,
        )

    @staticmethod
    def _parse_tool(payload: dict) -> ToolCall | None:
        name = payload.get("tool_name")
        if not isinstance(name, str) or not name:
            return None
        arguments = payload.get("tool_input")
        arguments = arguments if isinstance(arguments, dict) else {}
        command = arguments.get("command")
        return ToolCall(
            native_name=name,
            operation=_TOOL_OPERATIONS.get(name),
            command=command if isinstance(command, str) else None,
            raw_input=arguments,
        )

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        """The nested envelope, on stdout, with exit 0.

        Observed refusing by effect: with exactly this shape on stdout and an
        exit code of 0, the file the model was told to create was never created,
        Codex logged `Command blocked by PreToolUse hook: <reason>` and echoed
        the reason back verbatim — which is what proves the JSON was parsed as a
        verdict rather than failing closed on a parse error.

        Exit 2 is *not* the refusal channel it is for Claude Code. Codex's
        exit-code path was never exercised, so the adapter refuses the one way it
        was seen to refuse. `systemMessage`, `continue` and `suppressOutput` are
        Claude Code's own top-level keys and are not emitted here at all: none was
        observed being read, and a key Codex ignores is a channel a builtin
        believes it has.
        """
        support = _HOOK_EVENTS.get(event.event)
        verdict = decision.verdict
        if verdict is not None and (support is None or verdict not in support.verdicts):
            honoured = sorted(v.value for v in support.verdicts) if support else []
            raise ValueError(
                f"codex does not honour {verdict.value!r} on {event.event!r}; "
                f"honoured here: {honoured}"
            )
        native = support.native_name if support else event.event
        nested: dict[str, object] = {}
        if verdict is Verdict.DENY:
            nested["permissionDecision"] = verdict.value
            nested["permissionDecisionReason"] = decision.reason
        if decision.additional_context:
            nested["additionalContext"] = decision.additional_context
        if not nested:
            return HookOutput(stdout=None, stderr="", exit_code=0)
        body = {"hookSpecificOutput": {"hookEventName": native, **nested}}
        return HookOutput(stdout=json.dumps(body) + "\n", stderr="", exit_code=0)

    # --- config documents (ConfigPlanner) ---

    def config_targets(self) -> list[Path]:
        return [Path(_HOOKS_FILE)]

    def plan_config(
        self,
        hooks: dict[str, list[HookEntry]],
        servers: dict[str, dict],
        existing: dict[Path, str],
        *,
        binary: str | None = None,
    ) -> list[WriteOp]:
        """One document, replaced wholesale.

        `existing` is read for nothing, and that is the point of choosing
        `hooks.json`: the harness owns the entire file, so there is no foreign
        entry to preserve and no trust state to clobber. `binary` is ignored —
        the commands arrive already built, and the stamp that would name the
        writing launcher has nowhere to live in a document whose top level
        accepts only `description` and `hooks`.

        MCP is out of scope for the throwaway: `servers` is ignored, and an
        empty `hooks` plans no write at all rather than a write of an empty
        block, which would uninstall whatever the user declared themselves.
        """
        groups = self._hook_groups(hooks)
        if not groups:
            return []
        document = {"description": _DESCRIPTION, "hooks": groups}
        return [
            WriteOp(
                artifact=ConfigArtifact(
                    relative_path=Path(_HOOKS_FILE),
                    content=json.dumps(document, indent=2) + "\n",
                ),
                relative_path=Path(_HOOKS_FILE),
            )
        ]

    @staticmethod
    def _hook_groups(hooks: dict[str, list[HookEntry]]) -> dict[str, list[dict]]:
        """Canonical events -> Codex's `{event: [MatcherGroup, ...]}` block.

        One MatcherGroup per entry, in declaration order, because the trust key
        indexes both — `<file>:<event>:<group index>:<handler index>` — so the
        position an entry lands in is part of its identity across redeploys.

        `matcher` is omitted rather than emitted empty. It is honoured: a literal
        matching no tool suppressed the hook completely and silently. An empty
        string was never observed, and the observed form that fires on every tool
        call is the one with no key at all. The matcher is also part of the trust
        hash, so changing one un-trusts that hook.
        """
        groups: dict[str, list[dict]] = {}
        for event, entries in hooks.items():
            support = _HOOK_EVENTS.get(event)
            if support is None or not entries:
                continue
            groups[support.native_name] = [
                {
                    **({"matcher": entry.matcher} if entry.matcher else {}),
                    "hooks": [{"type": "command", "command": entry.command}],
                }
                for entry in entries
            ]
        return groups

    # --- the rest of the adapter surface ---

    def global_config_link(self) -> Path | None:
        """None, deliberately.

        Step 4 runs against a throwaway profile precisely so a failing gate
        cannot take a daily one with it. Linking `~/.codex` at the user's real
        Codex home would reintroduce exactly that blast radius.
        """
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        """`sessions/` is read off the observed `transcript_path`, which lands at
        `$CODEX_HOME/sessions/<yyyy>/<mm>/<dd>/rollout-<ts>-<session id>.jsonl`.
        No log or queue directory was observed."""
        return {"sessions": "sessions", "logs": "", "queue": ""}

    def system_doc_name(self) -> str:
        return "AGENTS.md"

    def process_name(self) -> str:
        return "codex"
