"""Codex CLI adapter — the whole eighteen-builtin surface, not step 4's gate.

The throwaway this replaces carried three builtins to a real Codex session to
make the canonical hook contract fail where it was going to fail. It did, twice
over: the contract froze at ADR-041, and the F8 translation gate then named five
builtins that deployed, ran, exited 0 and enforced nothing, because the
`ToolCall` this adapter handed them came back with the field they gate on
emptied. Closing that is what makes this the real one.

Everything here is pinned to behaviour **observed** against `codex-cli 0.154.0`
with `CODEX_HOME` pointed at a disposable directory. Where the binary was not
exercised, the adapter declares nothing rather than mirroring Claude Code: a
guess that reads as a capability is the failure this file exists to avoid, and
the previous revision of the design shipped six of them.

Two absences are decisions and not gaps, both recorded so a later reader does
not close them by symmetry with `ClaudeCodeAdapter`:

`SessionPinningAgent` is **unimplementable** here. `codex exec` at 0.154.0 has
no `--session-id`; six candidate spellings were rejected by the argument parser,
`ConfigToml`'s 101 fields carry no session id, and the decisive behavioural run
is `CODEX_SESSION_ID=<fixed uuid> codex exec --json` exiting 0 while
`thread.started` carries a UUIDv7 Codex generated. The id is born on Codex's
side, so the harness reconciles it after the fact or not at all.

`HeadlessAgent` is **unclaimed**, which is weaker and deliberate. `codex exec
--json` is read off the binary's strings and has never been driven end to end by
the harness; declaring the Protocol would make `lh exec` route work to a parser
nobody has fed. It waits on a run, not on a design decision.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lazy_harness.agents.base import (
    ConfigArtifact,
    FileEdit,
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


def _is_harness_written(raw: str | None) -> bool:
    """Whether this `hooks.json` is one the harness produced.

    The `description` stamp is the whole test, because it is the only key
    Codex's schema leaves free at the top level. A file that does not parse is
    *not* ours: the harness only ever writes `json.dumps` output.
    """
    if raw is None:
        return False
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(document, dict) and document.get("description") == _DESCRIPTION


def _as_toml(value: object) -> object:
    """A plain value as tomlkit items, so nested dicts land as tables.

    An MCP entry's `env` is a dict inside a dict. Assigned raw, tomlkit renders
    it as an inline table, which parses back identically but reads nothing like
    the rest of the file — and the file is one the user opens by hand.
    """
    import tomlkit

    if isinstance(value, dict):
        table = tomlkit.table()
        for key, item in value.items():
            table[key] = _as_toml(item)
        return table
    return value


class CodexConfigUnreadableError(RuntimeError):
    """`config.toml` exists and does not parse, so the merge cannot be made safe.

    Replacing it wholesale is the one option that is worse than doing nothing:
    the file carries `[projects.*]` trust levels and `[hooks.state]` approval
    hashes that Codex wrote as the user granted them, and neither can be
    reconstructed. A missing `[mcp_servers]` block costs one redeploy.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"{CONFIG_FILE} does not parse as TOML ({detail}). It carries project "
            f"trust and hook approvals that cannot be reconstructed, so it is left "
            f"untouched. Fix the file and re-run."
        )


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

# Codex's native edit tool, and the vocabulary of the blob it arrives with.
#
# `apply_patch`'s `tool_input` is `{"command": "<patch text>"}` — the *same* key
# `Bash` uses, carrying something that is not a shell command at all (probe 4c,
# 0.154.0). The three section headers are the format's; only `*** Update File:`
# was ever observed. `_parse_patch` recognises all three because it has to
# delimit sections correctly either way, and a header it did not know would
# swallow the next file's body into the previous file's hunks.
_APPLY_PATCH = "apply_patch"
_PATCH_END = "*** End Patch"
_SECTION_HEADERS: dict[str, str] = {
    "*** Update File: ": "update",
    "*** Add File: ": "add",
    "*** Delete File: ": "delete",
}


def _hunk_pair(lines: list[str]) -> tuple[str, str] | None:
    """One `@@` hunk as the `(old, new)` pair `FileEdit.replacements` holds.

    Unified-diff semantics, because that is what the pair is replayed through:
    `pre_tool_use_memory_size.py:148` does `current.replace(old, new)` against
    the file on disk, so a context line dropped from either side leaves an `old`
    that matches nothing and a prediction of no change at all. Context lines go
    on **both** sides; `-` lines only on the left, `+` only on the right.

    `None` for a hunk that changes nothing, which keeps a pure-context hunk from
    contributing an identity replacement.
    """
    old: list[str] = []
    new: list[str] = []
    for line in lines:
        marker, text = (line[:1], line[1:]) if line else (" ", "")
        if marker == "-":
            old.append(text)
        elif marker == "+":
            new.append(text)
        else:
            old.append(text)
            new.append(text)
    before, after = "\n".join(old), "\n".join(new)
    return None if before == after else (before, after)


def _parse_patch(blob: str) -> tuple[FileEdit, ...]:
    """The `*** Update File:` / `*** Add File:` sections of a blob, as `FileEdit`s.

    The one piece without which mapping `apply_patch` to `MODIFY_FILE` revives
    nothing: five builtins gate on `operation` or on the tool name and then die
    iterating `tool.edits`, which stayed `()` for every tool this adapter parsed
    until this function existed.

    **A `*** Delete File:` section produces no `FileEdit`, deliberately.**
    `FileEdit` carries `is_create` and no counterpart, so a delete emitted as an
    edit tells every reader the path is still there — `post_tool_use_format`
    would run a formatter over a file that is gone. Widening `FileEdit` is the
    honest fix and it is not this step's: the delete spelling is the format's,
    not one any probe has seen Codex emit (evidence §2).

    Anything that is not patch text yields `()`. The blob is model-authored and
    arrives on the same key a shell command does, so "unparseable" is an
    ordinary input here, never an error.
    """
    edits: list[FileEdit] = []
    kind: str | None = None
    path: Path | None = None
    hunks: list[list[str]] = []

    def flush() -> None:
        if kind is None or path is None:
            return
        if kind == "update":
            pairs = tuple(p for h in hunks if (p := _hunk_pair(h)) is not None)
            edits.append(FileEdit(path=path, replacements=pairs))
        elif kind == "add":
            body = "".join(
                line[1:] + "\n" for hunk in hunks for line in hunk if line.startswith("+")
            )
            edits.append(FileEdit(path=path, is_create=True, content=body))

    for line in blob.splitlines():
        header = next(
            (
                (k, line[len(prefix) :])
                for prefix, k in _SECTION_HEADERS.items()
                if line.startswith(prefix)
            ),
            None,
        )
        if header is not None:
            flush()
            kind, path, hunks = header[0], Path(header[1].strip()), []
            continue
        if kind is None:
            continue
        if line == _PATCH_END:
            flush()
            kind, path, hunks = None, None, []
            continue
        if line.startswith("@@"):
            hunks.append([])
            continue
        if kind == "delete":
            continue
        if not hunks:
            hunks.append([])
        hunks[-1].append(line)
    flush()
    return tuple(edits)


# Codex normalises its native tool name to Claude's on the hook wire: the model's
# own reasoning in the same transcript says it is calling `exec_command`, and the
# payload says `Bash`. A tool absent here parses with `operation=None`, which is
# "this ran, and no builtin has been written to guard it", not "this is
# harmless".
#
# Two entries, because Codex has two edit paths and picks between them
# non-deterministically (six runs, 0.154.0, `specs/designs/codex-evidence.md`
# §2). `apply_patch` is the native one, and probe 4c caught it firing
# `PreToolUse` with that literal name. The other is `Bash` running a python
# heredoc, and it is **deliberately not** mapped to `MODIFY_FILE`: its
# `tool_input.command` is an arbitrary shell script with no path to extract, so
# from a hook's point of view it is a command whatever it goes on to write.
# Mapping it would hand five builtins a `MODIFY_FILE` they cannot act on and an
# `edits` tuple that is empty for a structural reason. Half of Codex's edits are
# therefore ungateable as edits, and that is a property of the agent, not a gap
# here.
_TOOL_OPERATIONS: dict[str, Operation] = {
    "Bash": Operation.RUN_COMMAND,
    _APPLY_PATCH: Operation.MODIFY_FILE,
}

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
#
# Public because `agents/codex_trust.py` reads the same two documents back:
# the trust key embeds the declaring file's path, so a second spelling of
# either name is a report keyed on a file nothing writes.
HOOKS_FILE = "hooks.json"

# The file Codex writes to *itself*, mid-session. The adapter merges into it
# and never owns it — see `_plan_mcp` for what that costs and buys.
CONFIG_FILE = "config.toml"
_MCP_SECTION = "mcp_servers"

# The only free-text slot the document has: the top level accepts `description`
# and `hooks` and nothing else — any other key is a parse error that drops every
# hook in the file behind one warning. It deliberately carries no version. The
# trust key is scoped to this file, so a stamp that churns per release rewrites
# the declaring file on every upgrade, and whether that disturbs the stored
# hashes was never measured. Nothing is gained by finding out: the harness owns
# the whole file, so it needs no marker to recognise its own entries.
_DESCRIPTION = "Managed by lazy-harness. Edits are overwritten on the next deploy."


def trust_keys(hooks_file: Path, raw: str) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Codex's trust-state key for every handler a `hooks.json` declares.

    The formula is `<absolute path of the declaring file>:<snake_case event>:<group
    index>:<handler index>`, **measured** on 0.154.0 by the probe that found a
    byte-identical handler reading `Trusted` from `hooks.json` while the
    `config.toml` declaration of the same thing read `new · review required`,
    both carrying the same `trusted_hash`. Two details that probe settled and
    this function depends on: the key uses the **snake_case** event name even
    though the declaration must be PascalCase — both casings live in one file,
    in different roles — and both indices are *positions*, which is why a
    redeploy that reorders a group re-prompts for everything below it.

    The path is resolved: a relative one keys every hook under a string Codex
    never wrote, and every hook would then read untrusted forever.

    Returns `(declared, ignored)`. `declared` pairs each key with a human label,
    because a key is an absolute path plus three integers and says nothing to a
    reader. `ignored` names the event keys in the document that this Codex does
    not deliver — a hand-edited file can carry anything, and silently skipping
    one would report "all trusted" over a declaration nobody looked at.

    Anything that is not the expected shape declares nothing. This reads a file
    on the user's disk to build a diagnostic; raising here would take the twelve
    other sections of `lh doctor` down with it.
    """
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return (), ()
    if not isinstance(document, dict):
        return (), ()
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return (), ()

    canonical = {support.native_name: name for name, support in _HOOK_EVENTS.items()}
    declaring = hooks_file.resolve()
    declared: list[tuple[str, str]] = []
    ignored: list[str] = []
    for native, groups in hooks.items():
        event = canonical.get(str(native))
        if event is None:
            ignored.append(str(native))
            continue
        if not isinstance(groups, list):
            continue
        for group_index, group in enumerate(groups):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler_index in range(len(handlers)):
                declared.append(
                    (
                        f"{declaring}:{event}:{group_index}:{handler_index}",
                        f"{event}[{group_index}]",
                    )
                )
    return tuple(declared), tuple(ignored)


class CodexAdapter:
    """Codex CLI — the full `AgentAdapter` and `ConfigPlanner` surface."""

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
        command = command if isinstance(command, str) else None
        if name == _APPLY_PATCH:
            # `command` is left unset on purpose. Two builtins read it as shell
            # text — `pre_tool_use_security.py:362` and
            # `pre_tool_use_git_scope.py:402` both scan `tool.command` for shell
            # syntax — and a patch blob would put the *content of an edit* in
            # front of a command denylist, matching on lines the model is
            # writing into a file rather than on anything being executed. The
            # blob stays reachable through `raw_input` for an adapter; a builtin
            # reading it there is a normalisation that failed, which is what
            # that field's own docstring says.
            return ToolCall(
                native_name=name,
                operation=_TOOL_OPERATIONS.get(name),
                edits=_parse_patch(command) if command else (),
                raw_input=arguments,
            )
        return ToolCall(
            native_name=name,
            operation=_TOOL_OPERATIONS.get(name),
            command=command,
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
        """Two files, owned on two different terms.

        `hooks.json` is the harness's outright — it carries declarations and
        nothing else, which is what lets it be replaced wholesale and retired
        when it is no longer generated. `config.toml` is the user's and Codex's,
        and the adapter merges one section of it.

        Hook declarations never cross that line. Codex persists `[hooks.state]`
        trust hashes into `config.toml` next to `[projects.*]`, and the trust key
        is `<declaring file>:<event>:<group>:<handler>` — path-scoped — so moving
        a declaration between the two representations re-prompts for every hook
        in the file even though the hash is unchanged (probe, 0.154.0). MCP has
        no second home: `[mcp_servers.<id>]` is where Codex reads servers, so the
        only choice there is to merge carefully or not to ship them at all.
        """
        return [Path(HOOKS_FILE), Path(CONFIG_FILE)]

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

        `binary` is ignored — the commands arrive already built, and the stamp
        that would name the writing launcher has nowhere to live in a document
        whose top level accepts only `description` and `hooks`.
        """
        ops: list[WriteOp] = []
        hooks_op = self._plan_hooks(hooks, existing.get(Path(HOOKS_FILE)))
        if hooks_op is not None:
            ops.append(hooks_op)
        mcp_op = self._plan_mcp(servers, existing.get(Path(CONFIG_FILE)))
        if mcp_op is not None:
            ops.append(mcp_op)
        return ops

    def _plan_hooks(
        self, hooks: dict[str, list[HookEntry]], existing_raw: str | None
    ) -> WriteOp | None:
        """Write the declarations, or retire the file the harness used to write.

        An empty `hooks` plans no write rather than a write of an empty block:
        the latter would uninstall whatever the user declared themselves.

        It does plan a *delete*, but only of a document this harness wrote —
        recognised by the `description` stamp, which is the only marker the
        format has room for. Keying the delete on the file merely existing would
        eat a `hooks.json` the user wrote by hand the first time a profile
        configured no harness hooks, and that file is exactly where a Codex user
        declares their own.
        """
        groups = self._hook_groups(hooks)
        if not groups:
            if _is_harness_written(existing_raw):
                return WriteOp(artifact=None, relative_path=Path(HOOKS_FILE))
            return None
        document = {"description": _DESCRIPTION, "hooks": groups}
        return WriteOp(
            artifact=ConfigArtifact(
                relative_path=Path(HOOKS_FILE),
                content=json.dumps(document, indent=2) + "\n",
            ),
            relative_path=Path(HOOKS_FILE),
        )

    def _plan_mcp(self, servers: dict[str, dict], existing_raw: str | None) -> WriteOp | None:
        """Merge `[mcp_servers.<id>]` into a file the harness does not own.

        tomlkit rather than `tomli_w`, and a keyed update rather than a rebuild,
        for the same reason: everything not named here has to come back out
        byte-for-byte. `tomli_w.dumps` of a parsed document drops every comment
        and reorders nothing it was not asked to, but it *does* rewrite the whole
        file — and this file is where Codex records that the user trusted a
        directory (`[projects."<abs path>"].trust_level`) and approved a hook
        (`[hooks.state.<key>].trusted_hash`). Neither is reconstructible, and no
        test written against a fixture of our own shape would notice them going.

        No servers plans no write. `lh deploy-hooks` runs the cycle with
        `servers` blanked, and reserialising this file on that path would churn
        the user's document for nothing.
        """
        if not servers:
            return None

        import tomlkit

        try:
            document = tomlkit.parse(existing_raw or "")
        except Exception as exc:  # tomlkit raises several distinct parse errors
            raise CodexConfigUnreadableError(str(exc)) from exc

        section = document.get(_MCP_SECTION)
        if not isinstance(section, dict):
            section = tomlkit.table(is_super_table=True)
            document[_MCP_SECTION] = section

        preserved = [f"{_MCP_SECTION}: {name}" for name in section if name not in servers]
        projects = document.get("projects")
        if isinstance(projects, dict):
            preserved.extend(f"projects: {path}" for path in projects)

        for name, entry in servers.items():
            section[name] = _as_toml(entry)

        return WriteOp(
            artifact=ConfigArtifact(
                relative_path=Path(CONFIG_FILE),
                content=tomlkit.dumps(document),
            ),
            relative_path=Path(CONFIG_FILE),
            preserved=preserved,
        )

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
        """None — and the reason is no longer the throwaway's.

        Step 4 answered `None` to keep a failing gate from taking a daily
        profile with it, and `core/paths.py:162-171` records that the reasoning
        did not hold: resolution's last resort is `~/.<agent name>`, so a hook
        running under a Codex profile with no `CODEX_HOME` set wrote into
        `~/.codex` anyway — the directory `None` was supposedly protecting.

        The answer survives its justification because a better one arrived.
        `ensure_symlink` **renames an existing target to `<name>.bak`** before
        linking (`deploy/symlinks.py:16-21`), and `~/.codex` is not an empty
        mount point: it holds `auth.json`, and the `config.toml` carrying the
        `[hooks.state]` approvals the user granted by hand and the `[projects.*]`
        trust levels beside them. None of that is reconstructible, which is the
        same reason `_plan_mcp` merges that file instead of owning it. Claude
        Code can link `~/.claude` because the harness owns what is under it;
        Codex's home is shared with the vendor.
        """
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        """`sessions/` is read off the observed `transcript_path`, which lands at
        `$CODEX_HOME/sessions/<yyyy>/<mm>/<dd>/rollout-<ts>-<session id>.jsonl`.
        No log or queue directory was observed."""
        return {"sessions": "sessions", "logs": "", "queue": ""}

    def credentials_file(self) -> str | None:
        """None — the path is on record, the shape is not.

        `specs/designs/codex-evidence.md` names `~/.codex/auth.json`; all six
        probes copy it into their disposable `CODEX_HOME`. None of them opened
        it. The preflight parses Claude Code's `claudeAiOauth` envelope, so
        answering `"auth.json"` here would route this file at a parser that
        cannot read it and report "unexpected shape" — the same conflation
        `None` exists to remove. The probe that would change this answer is
        listed with the change that added the member (ADR-045 A4).
        """
        return None

    def system_docs(self) -> list[Path]:
        """`AGENTS.md`, the format Codex helped standardise — one destination."""
        return [Path("AGENTS.md")]

    def process_name(self) -> str:
        return "codex"
