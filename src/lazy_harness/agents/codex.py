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
import re
import shutil
import tomllib
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

from lazy_harness.agents.base import (
    Bypass,
    ConfigArtifact,
    FileEdit,
    HookDecision,
    HookEntry,
    HookEvent,
    HookOutput,
    HookOwnership,
    HookSupport,
    Operation,
    SessionIdentity,
    Signal,
    TokenUsage,
    ToolCall,
    TranscriptEvent,
    Verdict,
    WriteOp,
)
from lazy_harness.core.paths import expand_path

if TYPE_CHECKING:
    from collections.abc import Iterator


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


class CodexHooksUnreadableError(RuntimeError):
    """`hooks.json` cannot be merged without risking foreign declarations."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"{HOOKS_FILE} cannot be merged safely ({detail}), so it is left untouched. "
            "Fix the file and re-run."
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
# 0.154.0). Two of the three section headers are now observed from the binary:
# `*** Update File:` (probe 4c, and two of them in one blob at probe 5) and
# `*** Delete File:` (probe 6, one section, no diff body, the file removed from
# disk). `*** Add File:` remains the format's alone, and `_parse_patch`
# recognises it for the same reason it always did — a header it did not know
# would swallow the next file's body into the previous file's hunks.
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


class _Patch(NamedTuple):
    """What one `apply_patch` blob says, in the two shapes `ToolCall` keeps apart.

    Named rather than a bare pair: the whole point of ADR-046 is that these two
    must not be confused, and an unpacking order is a poor place to keep that.
    """

    edits: tuple[FileEdit, ...]
    deletes: tuple[Path, ...]


def _parse_patch(blob: str) -> _Patch:
    """A blob's file sections, split into the edits and the deletions.

    The one piece without which mapping `apply_patch` to `MODIFY_FILE` revives
    nothing: five builtins gate on `operation` or on the tool name and then die
    iterating `tool.edits`, which stayed `()` for every tool this adapter parsed
    until this function existed.

    **A `*** Delete File:` section goes to `deletes`, never to `edits`.** Probe
    6 measured the shape — one section, that literal header, no diff body, the
    file removed from disk (`specs/designs/codex-evidence.md` §2) — and ADR-046
    decided where it lands. Emitting it as a `FileEdit` would tell every reader
    the path is still there, and `post_tool_use_format` would run a formatter
    over a file that is gone.

    Section order is preserved within each half and not across them: every
    section of one blob is applied by one call, so which file came first carries
    no semantics and no reader of either collection orders work by it.

    Anything that is not patch text yields two empty tuples. The blob is
    model-authored and arrives on the same key a shell command does, so
    "unparseable" is an ordinary input here, never an error.
    """
    edits: list[FileEdit] = []
    deletes: list[Path] = []
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
        elif kind == "delete":
            deletes.append(path)

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
    return _Patch(tuple(edits), tuple(deletes))


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


# --- rollout transcript (TranscriptReader) ---
#
# Every name below was measured off rollout files `codex-cli 0.154.0` wrote on
# this machine, recorded as §5 of `specs/designs/codex-evidence.md` (`[log]`).
# A transcript schema is valid only for the version it was observed on, so the
# version is on record in both places and there is no version switch here: a
# second version has never been seen, and a branch nothing has exercised is the
# guess this adapter exists to avoid.

_ROLLOUT_GLOB = "rollout-*.jsonl"
# The uuid v7 that closes a rollout's file name. Measured: it equals
# `session_meta.id` in 15/15 rollouts, so the session is identifiable without
# opening the file — which matters on a tree of thousands.
_ROLLOUT_SESSION = re.compile(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(?P<session>.+)$")

# `developer` is the third role in the stream and is deliberately not here. It
# is Codex's instruction channel — the composed `AGENTS.md` and config text,
# re-sent every turn — not a turn anyone took. `knowledge/session_export.py:56`
# labels every non-`user` role as the model speaking, so emitting it would write
# the profile's own instructions into the exported conversation.
_MESSAGE_ROLES: frozenset[str] = frozenset({"user", "assistant"})

# Two spellings for one concept, split by direction: `input_text` on user and
# developer turns, `output_text` on assistant turns.
_TEXT_BLOCKS: frozenset[str] = frozenset({"input_text", "output_text"})

# `custom_tool_call` carries a bare string argument, `function_call` a JSON one.
# Their `*_output` counterparts are results, not calls, and are not read: the
# signal is the call, and `call_id` is what pairs the two for a consumer that
# wants both.
_TOOL_CALL_KINDS: frozenset[str] = frozenset({"custom_tool_call", "function_call"})


def _as_int(value: object) -> int | None:
    """`value` if it is a real int. Unlike `or`, a legitimate 0 survives."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _turn_context_model(entry: dict) -> str | None:
    """The model a `turn_context` line declares, or None if it declares none.

    `turn_context` is the only kind in a 0.154.0 rollout that names the model:
    measured over 15 sessions, 23 of these lines carried `payload.model` as a
    non-empty string every time, and one model per file. It is read for this
    field alone — the rest of the payload (cwd, sandbox, approvals) duplicates
    nothing a signal is defined over, so reading it does not violate ADR-048's
    one-stream-per-signal rule.

    Never raises and never guesses: a release that renames the key, or writes
    it as a number, leaves the model unknown rather than stringified.
    """
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) and model else None


def _charged_input(usage: dict) -> int | None:
    """The input Codex charged at full rate: its `input_tokens` less the cache.

    A record that reported no input keeps `None` — the absent-counter
    distinction `TokenUsage` exists to preserve — and one that reported input
    without a cached figure is taken at face value.
    """
    reported = _as_int(usage.get("input_tokens"))
    if reported is None:
        return None
    cached = _as_int(usage.get("cached_input_tokens"))
    if cached is None:
        return reported
    return max(reported - cached, 0)


def _rollout_timestamp(value: object) -> datetime | None:
    """The envelope's `timestamp`, or None for anything that is not one.

    Observed as `2026-09-16T12:02:13.926Z` — UTC, milliseconds, `Z` rather than
    an offset, which `fromisoformat` accepts from 3.11 on. Never raises: a later
    release is allowed to change this field, and losing the time of one entry
    must not lose the entry.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _tool_input(kind: str, payload: dict) -> dict:
    """The call's argument, as the dict `_parse_tool` reads — never as `command`.

    The two kinds spell their argument differently and only one of them is
    structured. `function_call.arguments` is a JSON object, so it is parsed and
    handed over as-is. `custom_tool_call.input` is a **bare string**, and at
    0.154.0 the only tool taking that path is `exec`, whose argument is a
    *TypeScript program* for Codex's cell runtime — measured: 154 of 154 calls
    multiline, every one containing `await `, first tokens `text` / `const` /
    `for` / `await`, not one shell-shaped.

    So it is wrapped under `input` rather than mapped onto `command`, and the
    consequence is deliberate: `_parse_tool` reads `command` only, so the
    program lands in `raw_input` and `ToolCall.command` stays `None`.
    `pre_tool_use_security.py` and `pre_tool_use_git_scope.py` both scan
    `tool.command` as shell text — the same reason `_parse_tool` refuses to put
    a patch blob there, and the same failure if a program went in (ADR-048).
    """
    if kind == "function_call":
        arguments = payload.get("arguments")
        if not isinstance(arguments, str):
            return {}
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    raw = payload.get("input")
    return {"input": raw} if isinstance(raw, str) else {}


def _rollout_text(content: object) -> str:
    """A turn's text, with every non-text block dropped.

    `content` is always a list here — unlike Claude Code, Codex never puts a
    bare string on a turn — but a non-list still degrades to empty rather than
    raising, since this runs over a file another process is writing.
    """
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") in _TEXT_BLOCKS
        and isinstance(block.get("text"), str)
    )


# The file the harness owns, and the decision behind it.
#
# Codex loads hooks from `$CODEX_HOME/config.toml` *and* `$CODEX_HOME/hooks.json`,
# additively, and asks the deployer to pick one. The harness picks `hooks.json`
# because `config.toml` is not ours: Codex writes the `[hooks.state]` table of
# `trusted_hash` entries back into it, alongside `[projects.*]` trust levels, so a
# deploy that owns that file can silently revoke the user's own trust decisions.
# `hooks.json` holds declarations from the harness, native installers and users.
# The adapter therefore merges matcher groups and owns only builtins proven by
# its versioned description envelope (or the legacy whole-file migration stamp).
#
# **The choice is frozen at the first deploy.** The trust state key is
# `<absolute path of the declaring file>:<snake_case of Codex's own event
# name>:<group index>:<handler index>` — path-scoped. The *hash* is stable across
# the two representations, but the key is not, so moving a hook from `hooks.json`
# to `config.toml` (or back) re-prompts for every hook even though nothing about
# the hook changed. Switching representation costs a full re-trust; it is not a
# refactor.
#
# Public because `agents/codex_trust.py` reads the same two documents back:
# the trust key embeds the declaring file's path, so a second spelling of
# either name is a report keyed on a file nothing writes.
HOOKS_FILE = "hooks.json"

# The file Codex writes to *itself*, mid-session. The adapter merges into it
# and never owns it — see `_plan_mcp` for what that costs and buys.
CONFIG_FILE = "config.toml"
_MCP_SECTION = "mcp_servers"

# The old stamp proves that a whole-file planner generated the document. New
# documents carry a versioned provenance envelope. Codex 0.155.1 was probed via
# `hooks/list`: description-only changes preserve key, currentHash and trust.
_LEGACY_DESCRIPTION = "Managed by lazy-harness. Edits are overwritten on the next deploy."
_PROVENANCE_PREFIX = "lazy-harness-hook-ownership:"
_OWNERSHIP_VERSION = 1


def _parse_hooks_document(raw: str | None) -> dict:
    """Parse the shared Codex document, refusing every lossy shape."""
    if raw is None:
        return {}
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CodexHooksUnreadableError(f"invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CodexHooksUnreadableError(f"top level is {type(document).__name__}, expected object")
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        raise CodexHooksUnreadableError(f"hooks is {type(hooks).__name__}, expected object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise CodexHooksUnreadableError(
                f"hooks.{event} is {type(groups).__name__}, expected array"
            )
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                raise CodexHooksUnreadableError(
                    f"hooks.{event}[{index}] is {type(group).__name__}, expected object"
                )
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                raise CodexHooksUnreadableError(
                    f"hooks.{event}[{index}].hooks is {type(handlers).__name__}, expected array"
                )
            if not all(isinstance(handler, dict) for handler in handlers):
                raise CodexHooksUnreadableError(
                    f"hooks.{event}[{index}].hooks contains a non-object handler"
                )
    return document


def _parse_provenance(description: object) -> tuple[set[str], dict[tuple[str, int], dict]]:
    """Return recorded launchers and exact managed groups from a valid envelope."""
    if not isinstance(description, str) or not description.startswith(_PROVENANCE_PREFIX):
        return set(), {}
    try:
        envelope = json.loads(description.removeprefix(_PROVENANCE_PREFIX))
    except (json.JSONDecodeError, ValueError):
        return set(), {}
    if not isinstance(envelope, dict) or envelope.get("version") != _OWNERSHIP_VERSION:
        return set(), {}
    launchers = envelope.get("launchers")
    managed = envelope.get("managed")
    if not isinstance(launchers, list) or not all(
        isinstance(launcher, str) and launcher for launcher in launchers
    ):
        return set(), {}
    if not isinstance(managed, list):
        return set(), {}
    ownership: dict[tuple[str, int], dict] = {}
    for item in managed:
        if not isinstance(item, dict):
            return set(), {}
        event = item.get("event")
        index = item.get("index")
        group = item.get("group")
        if (
            not isinstance(event, str)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or not isinstance(group, dict)
            or (event, index) in ownership
        ):
            return set(), {}
        ownership[(event, index)] = group
    return set(launchers), ownership


def _group_commands(group: dict) -> list[str]:
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return []
    return [
        command
        for handler in handlers
        if isinstance(handler, dict) and isinstance((command := handler.get("command")), str)
    ]


def _group_label(event: str, index: int, group: dict) -> str:
    commands = _group_commands(group)
    detail = ", ".join(commands) if commands else "<unrecognized group>"
    return f"{event}[{index}]: {detail}"


def _group_identity(
    event: str, group: dict
) -> tuple[str, object, tuple[tuple[object, object], ...]] | None:
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return None
    identities: list[tuple[object, object]] = []
    for handler in handlers:
        if not isinstance(handler, dict):
            return None
        identities.append((handler.get("type"), handler.get("command")))
    return event, group.get("matcher"), tuple(identities)


def _group_is_harness_builtin(event: str, group: dict, *, binaries: set[str]) -> bool:
    """Recognise exactly one matcher group the Codex generator can emit."""
    from lazy_harness.hooks.loader import builtin_name_from_command, resolve_builtin_spec

    canonical = next(
        (name for name, support in _HOOK_EVENTS.items() if support.native_name == event), None
    )
    if canonical is None or not set(group) <= {"matcher", "hooks"}:
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list) or len(handlers) != 1:
        return False
    handler = handlers[0]
    if (
        not isinstance(handler, dict)
        or set(handler) != {"type", "command"}
        or handler.get("type") != "command"
    ):
        return False
    command = handler.get("command")
    if not isinstance(command, str):
        return False
    name = builtin_name_from_command(command, binaries=binaries)
    if name is None:
        return False
    spec = resolve_builtin_spec(name)
    if spec is None:
        return False
    matcher = spec.matcher_for(canonical)
    expected = {"hooks": [handler], **({"matcher": matcher} if matcher else {})}
    return group == expected


def _provenance_description(
    hooks: dict[str, list[dict]],
    owned: set[tuple[str, int]],
    *,
    launchers: set[str],
    previous: object,
) -> str:
    managed = [
        {"event": event, "index": index, "group": groups[index]}
        for event, groups in hooks.items()
        for index in range(len(groups))
        if (event, index) in owned
    ]
    envelope: dict[str, object] = {
        "version": _OWNERSHIP_VERSION,
        "launchers": sorted(launchers),
        "managed": managed,
    }
    if (
        isinstance(previous, str)
        and previous != _LEGACY_DESCRIPTION
        and not previous.startswith(_PROVENANCE_PREFIX)
    ):
        envelope["previous_description"] = previous
    elif isinstance(previous, str) and previous.startswith(_PROVENANCE_PREFIX):
        try:
            prior_envelope = json.loads(previous.removeprefix(_PROVENANCE_PREFIX))
        except (json.JSONDecodeError, ValueError):
            prior_envelope = None
        if isinstance(prior_envelope, dict) and isinstance(
            prior_envelope.get("previous_description"), str
        ):
            envelope["previous_description"] = prior_envelope["previous_description"]
    return _PROVENANCE_PREFIX + json.dumps(envelope, separators=(",", ":"), sort_keys=True)


def _owned_positions(
    document: dict, hooks: dict[str, list[dict]], *, binary: str
) -> tuple[set[tuple[str, int]], set[str]]:
    """Positions proven managed by provenance plus an all-builtin group."""
    from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY

    current = PurePosixPath(binary.replace("\\", "/")).name
    default = PurePosixPath(DEFAULT_HARNESS_BINARY.replace("\\", "/")).name
    description = document.get("description")
    if description == _LEGACY_DESCRIPTION:
        launchers = {default, current}
        return (
            {
                (event, index)
                for event, groups in hooks.items()
                for index, group in enumerate(groups)
                if _group_is_harness_builtin(event, group, binaries=launchers)
            },
            launchers,
        )

    launchers, recorded = _parse_provenance(description)
    owned = {
        (event, index)
        for (event, index), recorded_group in recorded.items()
        if event in hooks
        and index < len(hooks[event])
        and hooks[event][index] == recorded_group
        and _group_is_harness_builtin(event, hooks[event][index], binaries=launchers)
    }
    return owned, launchers | {current}


def _merge_hook_groups(
    existing: dict[str, list[dict]],
    managed: dict[str, list[dict]],
    external: dict[str, list[dict]],
    *,
    old_owned: set[tuple[str, int]],
) -> tuple[dict[str, list[dict]], set[tuple[str, int]], list[str], list[str]]:
    """Fill managed slots, preserve foreign positions, then ensure externals."""
    merged: dict[str, list[dict]] = {}
    new_owned: set[tuple[str, int]] = set()
    preserved: list[str] = []
    dropped: list[str] = []

    for event, existing_groups in existing.items():
        desired = list(managed.get(event, []))
        desired_index = 0
        event_owned = {index for name, index in old_owned if name == event}
        output: list[dict] = []

        for index, group in enumerate(existing_groups):
            if index in event_owned:
                if desired_index < len(desired):
                    output.append(desired[desired_index])
                    new_owned.add((event, len(output) - 1))
                    desired_index += 1
                else:
                    dropped.append(_group_label(event, index, group))
            else:
                output.append(group)
                preserved.append(_group_label(event, index, group))

        while desired_index < len(desired):
            output.append(desired[desired_index])
            new_owned.add((event, len(output) - 1))
            desired_index += 1
        if output:
            merged[event] = output

    for event, desired in managed.items():
        if event in existing:
            continue
        output = merged.setdefault(event, [])
        for group in desired:
            output.append(group)
            new_owned.add((event, len(output) - 1))

    for event, desired in external.items():
        output = merged.setdefault(event, [])
        for group in desired:
            identity = _group_identity(event, group)
            if identity is not None and any(
                _group_identity(event, candidate) == identity for candidate in output
            ):
                continue
            output.append(group)

    return merged, new_owned, preserved, dropped


def _trust_event_segment(native: str) -> str:
    """The event segment of a Codex trust key, from Codex's own name for it.

    snake_case of the **native** name, never of the harness's canonical one.
    The two agree for eight of the nine events and diverge for exactly one:
    canonical `session_stop` is native `Stop`, which Codex keys as `stop`.
    Deriving the segment from the canonical name made those six handlers read
    untrusted after the user had approved them, and their stored entries read
    orphaned — one mismatch counted twice, measured on `codex-cli 0.154.0`
    (`specs/designs/codex-evidence.md` §6.4).
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", native).lower()


def _canonical_event_names() -> dict[str, str]:
    """Codex's native (PascalCase) hook name -> the harness's canonical one.

    One mapping, shared by `trust_keys` and `_changed_hook_labels` — both read
    a `hooks.json` `hooks` block keyed on the native name and need to label
    entries the way a reader recognises them, and a second copy of this dict
    is exactly the kind of drift the repo's "one answer, one place" rule
    exists to stop.
    """
    native = {name: name for name in CODEX_EVENT_NAMES}
    native.update({support.native_name: name for name, support in _HOOK_EVENTS.items()})
    return native


def _changed_hook_labels(existing_raw: str | None, groups: dict[str, list[dict]]) -> list[str]:
    """Which declared matcher groups differ from what `existing_raw` has on disk.

    Per hook, not per file: `_hook_groups` already produces one dict per
    matcher group, keyed and ordered exactly as `hooks.json` stores them, so
    comparing group-by-group is exact and free — no reason to fall back to a
    whole-file diff. `existing_raw is None` (no file yet) makes every declared
    group changed, matching the "first deploy" row of the design's table.
    Labelled the same way `trust_keys` labels its own keys, so a `lh deploy`
    line and `lh doctor`'s naming of the same hook read as one vocabulary.
    """
    canonical = _canonical_event_names()
    existing_groups: dict[str, list] = {}
    if existing_raw is not None:
        try:
            document = json.loads(existing_raw)
        except (json.JSONDecodeError, ValueError):
            document = None
        if isinstance(document, dict):
            hooks = document.get("hooks")
            if isinstance(hooks, dict):
                existing_groups = hooks

    changed: list[str] = []
    for native in sorted(set(groups) | set(existing_groups)):
        event = canonical.get(native, native)
        new_list = groups.get(native, [])
        old_list = existing_groups.get(native)
        old_list = old_list if isinstance(old_list, list) else []
        for index in range(max(len(new_list), len(old_list))):
            new_group = new_list[index] if index < len(new_list) else None
            old_group = old_list[index] if index < len(old_list) else None
            if new_group != old_group:
                changed.append(f"{event}[{index}]")
    return changed


def trust_keys(hooks_file: Path, raw: str) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Codex's trust-state key for every handler a `hooks.json` declares.

    The formula is `<absolute path of the declaring file>:<snake_case of Codex's
    own event name>:<group index>:<handler index>`, **measured** on 0.154.0 by
    the probe that found a byte-identical handler reading `Trusted` from
    `hooks.json` while the `config.toml` declaration of the same thing read
    `new · review required`, both carrying the same `trusted_hash`. Two details
    that probe settled and this function depends on: the key uses the
    **snake_case** event name even though the declaration must be PascalCase —
    both casings live in one file, in different roles — and both indices are
    *positions*, which is why a redeploy that reorders a group re-prompts for
    everything below it.

    The segment is `_trust_event_segment(native)`, not the canonical name this
    adapter maps that native one to: the label is the harness's vocabulary, the
    key is Codex's, and `session_stop` is the event where the two differ.

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

    canonical = _canonical_event_names()
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
        segment = _trust_event_segment(str(native))
        for group_index, group in enumerate(groups):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler_index in range(len(handlers)):
                declared.append(
                    (
                        f"{declaring}:{segment}:{group_index}:{handler_index}",
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

    def skill_root(self, profile_config_dir: str) -> Path | None:
        """The host catalog observed on Codex 0.154.0 (ADR-059).

        Codex can explicitly disable host discovery in its feature table.  A
        malformed config is handled later by the config planner; it does not
        turn an unreadable opt-out into an asserted capability here.
        """
        config = self.config_dir(profile_config_dir) / "config.toml"
        try:
            raw = tomllib.loads(config.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return None
        features = raw.get("features")
        if isinstance(features, dict) and features.get("skip_host_skill_discovery") is True:
            return None
        return Path.home() / ".agents" / "skills"

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
            patch = _parse_patch(command) if command else _Patch((), ())
            return ToolCall(
                native_name=name,
                operation=_TOOL_OPERATIONS.get(name),
                edits=patch.edits,
                deletes=patch.deletes,
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
        """Two shared files, each merged under its native schema.

        `hooks.json` carries declarations from several owners; the adapter
        replaces only groups proven to be its builtins. `config.toml` is the
        user's and Codex's, and the adapter merges one section of it.

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
        """Plan the shared hook document and merged MCP/trust document."""
        from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY

        ops: list[WriteOp] = []
        hooks_op = self._plan_hooks(
            hooks,
            existing.get(Path(HOOKS_FILE)),
            binary=binary or DEFAULT_HARNESS_BINARY,
        )
        if hooks_op is not None:
            ops.append(hooks_op)
        mcp_op = self._plan_mcp(servers, existing.get(Path(CONFIG_FILE)))
        if mcp_op is not None:
            ops.append(mcp_op)
        return ops

    def _plan_hooks(
        self,
        hooks: dict[str, list[HookEntry]],
        existing_raw: str | None,
        *,
        binary: str,
    ) -> WriteOp | None:
        """Conservatively reconcile only proven harness-owned matcher groups."""
        document = _parse_hooks_document(existing_raw)
        existing_hooks = document.get("hooks", {})
        if not isinstance(existing_hooks, dict):  # guarded by the parser
            raise AssertionError("parsed hooks document lost its hooks object")

        managed = self._hook_groups(
            {
                event: [entry for entry in entries if entry.ownership is HookOwnership.HARNESS]
                for event, entries in hooks.items()
            }
        )
        external = self._hook_groups(
            {
                event: [entry for entry in entries if entry.ownership is HookOwnership.EXTERNAL]
                for event, entries in hooks.items()
            }
        )
        old_owned, launchers = _owned_positions(document, existing_hooks, binary=binary)

        if not managed and not external and not old_owned:
            return None

        groups, new_owned, preserved, dropped = _merge_hook_groups(
            existing_hooks,
            managed,
            external,
            old_owned=old_owned,
        )
        if not groups:
            return WriteOp(
                artifact=None,
                relative_path=Path(HOOKS_FILE),
                preserved=preserved,
                dropped=dropped,
                changed=_changed_hook_labels(existing_raw, groups),
            )

        if new_owned or old_owned:
            current = PurePosixPath(binary.replace("\\", "/")).name
            document["description"] = _provenance_description(
                groups,
                new_owned,
                launchers=launchers | {current},
                previous=document.get("description"),
            )
        elif existing_raw is None:
            document.pop("description", None)
        document["hooks"] = groups
        return WriteOp(
            artifact=ConfigArtifact(
                relative_path=Path(HOOKS_FILE),
                content=json.dumps(document, indent=2) + "\n",
            ),
            relative_path=Path(HOOKS_FILE),
            preserved=preserved,
            dropped=dropped,
            changed=_changed_hook_labels(existing_raw, groups),
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
        """None — and now because the shape IS on record, not because it is not.

        `~/.codex/auth.json` is fully measured (`codex-evidence.md` probe 8):
        `auth_mode: str`, `OPENAI_API_KEY: None`, `last_refresh: str`, and
        `tokens: {id_token, access_token, refresh_token, account_id}`, all
        strings. What the file does not carry, at any level, is an **expiry**.

        That is what keeps the answer at `None`. The preflight's `check_auth`
        derives its verdict from one — `refreshTokenExpiresAt` in Claude Code's
        envelope — so pointing it at this file could only ever produce
        "unexpected shape", which is the conflation `None` exists to remove.

        Deriving a verdict from the age of `last_refresh` would work, but it is
        a heuristic with a threshold nobody has measured: how stale can
        `last_refresh` be while the login is still alive? That needs its own
        probe and its own ADR, not this one.
        """
        return None

    def system_docs(self) -> list[Path]:
        """`AGENTS.md`, the format Codex helped standardise — one destination."""
        return [Path("AGENTS.md")]

    def bypass_argv(self, level: Bypass) -> list[str] | None:
        """Measured on codex-cli 0.154.0 — `codex-evidence.md` section 7, `[run]`.

        Seven candidates were driven against a fixture that writes outside the
        workspace to two targets: one under `$HOME`, one under a temp directory.
        Two targets rather than one because the Seatbelt policy permits temp
        writes under `workspace-write`, and a level scored on that alone reads
        as bypassed when the sandbox is still holding.

        ENABLE is `None`, and that is a measurement rather than a gap. Nothing
        on this version does what `--allow-dangerously-skip-permissions` does on
        Claude Code — change nothing about the turn while making the toggle
        reachable inside it. `baseline` and `-c approval_policy="never"` were
        indistinguishable: no command ran under either. `--approve-for-me` ran
        one, so it is already on.

        ACTIVATE is `--approve-for-me`: the command ran unattended, and the
        write outside the workspace was still refused. That is the definition —
        the prompt stops reaching the human, whatever sandbox exists stays.
        Worth naming precisely: this routes approvals through an automatic
        review, so it means "answered without you", not "always granted".

        NO_SANDBOX is the single combined flag, documented as "Skip all
        confirmation prompts and execute commands without sandboxing" — both
        halves, which is what "also remove the sandbox" asks for.
        `-s danger-full-access` alone also reached the `$HOME` target and is
        deliberately not the mapping: it strips the sandbox while leaving the
        approval policy at its default, so on the interactive launch `lh run`
        performs it would remove the sandbox and still prompt.

        Two limits on the evidence, both narrow. The probe drives `codex exec`
        because that is what can be measured non-interactively, while `lh run`
        execs the top-level `codex`; both flags above are on both commands, so
        the transfer is help-backed even though the behaviour is run-backed.
        And `-a/--ask-for-approval` is top-level only — `codex exec` refuses it
        with "unexpected argument '-a' found" (`[run]`), which is why it appears
        in no row here.

        `--dangerously-bypass-hook-trust` is deliberately absent from every row.
        It sits on the same help page and is a different axis: whether hooks run
        without persisted trust, not whether the model needs approval. Emitting
        it from `--bypass` would disable this harness's own guardrails as a side
        effect of a request about the agent's.
        """
        if level is Bypass.ACTIVATE:
            return ["--approve-for-me"]
        if level is Bypass.NO_SANDBOX:
            return ["--dangerously-bypass-approvals-and-sandbox"]
        return None

    def process_name(self) -> str:
        return "codex"

    # --- transcript reading (TranscriptReader) ---
    #
    # Pinned to the rollout format of **`codex-cli 0.154.0`**, measured rather
    # than assumed: `specs/designs/codex-evidence.md` §5 carries the kind
    # inventory this reads and the kinds it skips, from 15 real session files.
    #
    # `locate_sessions` exists for the after-the-fact scan only. A hook is
    # handed `transcript_path` outright in Codex's payload (evidence §1), so it
    # has no path to reconstruct.

    def signals(self) -> set[Signal]:
        """Three of the four. `GOAL_STATUS` is refused, and that is the decision.

        Codex 0.154.0 has no `/goal` and no marker anywhere in the rollout — no
        kind, no payload field, in any of the 15 sessions measured. Decision 11
        of `specs/designs/2026-09-13-multi-agent-harness-design.md` makes this
        set the thing a hook's declaration is checked against, so claiming the
        signal here would deploy `stop-verify-guard` onto Codex, where it would
        read a transcript that cannot carry a goal and approve every stop.
        """
        return {Signal.MESSAGES, Signal.TOOL_CALLS, Signal.TOKEN_USAGE}

    def locate_sessions(self, config_dir: Path, since: datetime | None) -> Iterator[Path]:
        """`<config_dir>/sessions/**/rollout-*.jsonl`, filtered by modification time.

        **Modification time, not the timestamp in the file name.** The name
        carries `rollout-<YYYY-MM-DD>T<HH-MM-SS>-<uuid>.jsonl`, and that stamp
        is the session's *start* in **local wall-clock with no offset** —
        measured: a file named `...T09-02-04-...` whose first record is
        `2026-09-16T12:02:13.926Z`, three hours apart on a UTC-3 host. So it
        answers neither question `since` asks, and parsing it as a time is wrong
        by whatever offset the machine that wrote it was on (ADR-048).

        Order is the filesystem's and is not promised; yielding as the walk
        proceeds is what keeps a sessions tree of thousands of files from being
        materialised to answer "any since Monday".
        """
        root = config_dir / (self.session_dirs()["sessions"] or "sessions")
        cutoff = since.timestamp() if since is not None else None
        try:
            for path in root.glob(f"**/{_ROLLOUT_GLOB}"):
                try:
                    if not path.is_file():
                        continue
                    if cutoff is not None and path.stat().st_mtime < cutoff:
                        continue
                except OSError:
                    continue
                yield path
        except OSError:
            return

    def session_identity(self, path: Path) -> SessionIdentity:
        """The session from the file name, the project from `session_meta.cwd`.

        A rollout path encodes a **date**, never a project — the tree is
        `sessions/YYYY/MM/DD/` — so the project has to come out of the file.
        `session_meta` is the first record written, and this stops at it rather
        than reading a log that can run to hundreds of megabytes to learn one
        string.

        The session id comes off the file name instead, which is measurably the
        same answer: the name's trailing uuid v7 equalled `session_meta.id` in
        15/15 rollouts. That keeps a session identifiable when the record is
        missing, half-written, or the file has since been removed — this must
        not raise, and a session named by its file beats a session lost.

        The project is `cwd` resolved the way every other subsystem resolves
        one, so a worktree bills to its repository rather than to a row per
        branch. A `cwd` that no longer exists still names its own directory,
        which is the right answer for a checkout that has been cleaned up.
        """
        from lazy_harness.core.project_identity import repo_name

        match = _ROLLOUT_SESSION.match(path.stem)
        session_id = match.group("session") if match else path.stem

        project: str | None = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict) or entry.get("type") != "session_meta":
                        continue
                    payload = entry.get("payload")
                    if isinstance(payload, dict):
                        cwd = payload.get("cwd")
                        if isinstance(cwd, str) and cwd:
                            project = repo_name(Path(cwd))
                    break
        except OSError:
            pass
        return SessionIdentity(session_id=session_id, project=project)

    def read(self, path: Path) -> Iterator[TranscriptEvent]:
        """One rollout, line by line, yielding only what a signal is defined over.

        Lazy for the same two reasons the Claude Code reader is: nothing is
        opened until the first `next()`, so a hook that builds its reader when
        it starts still judges the file as of the moment it decides; and a
        consumer looking for one marker stops at the first hit.

        `errors="replace"` rather than a strict decode: one byte Codex failed to
        write cleanly would otherwise raise mid-iteration and cost every line
        after it.

        **One event here depends on a line already passed.** No usage record
        names the model; `turn_context` does, on its own line, earlier. So the
        last model declared is carried forward onto everything that follows it
        — the only backward reference in either reader, and the reason this
        loop and not `_events_from` owns the state.

        That state is a local of this generator and never an attribute of the
        adapter. `registry.py` builds a bare `cls()`, so one instance serves
        every profile and two reads can be open at once; held on `self`, the
        second would inherit the first's model and bill one session's tokens
        under another session's name.
        """
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            return
        carried_model: str | None = None
        with handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # A corrupt line, or the half-written last one of a live
                    # session. Both are ordinary; neither ends the read.
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "turn_context":
                    # Read for one field and delivered as nothing: no signal is
                    # defined over it. A context naming no usable model leaves
                    # the previous one standing rather than blanking it — the
                    # turns it introduces did run on something.
                    declared = _turn_context_model(entry)
                    if declared is not None:
                        carried_model = declared
                    continue
                yield from self._events_from(entry, carried_model)

    def _events_from(self, entry: dict, model: str | None = None) -> Iterator[TranscriptEvent]:
        """Every event one rollout line carries — at most one, in this format.

        `model` is what the last `turn_context` declared, carried forward by
        `read()`; `None` until one has been seen.

        A rollout is two interleaved streams, and **the same fact appears in
        both**: the model's own `response_item` items and the UI's `event_msg`
        ones. A turn is a `response_item/message` *and* an
        `event_msg/item_completed` with an `AgentMessage` item; a turn's tokens
        are a `token_usage_record` *and* an `event_msg/token_count`. Only one
        side is read per signal, or every consumer counting turns or summing
        tokens doubles its answer (ADR-048). The `event_msg` side is the one
        dropped: it is the TUI's rendering — `completed_at_ms`,
        `formatted_output` — and it carries no `call_id` to pair a call with its
        result.
        """
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return
        when = _rollout_timestamp(entry.get("timestamp"))
        # `==` rather than a membership test: a `type` of `[]` or `{}` is valid
        # JSON, and `in` hashes its left operand, so the lookup alone would
        # raise out of this generator and end the read.
        kind = entry.get("type")
        if kind == "response_item":
            yield from self._response_item_events(entry, payload, when, model)
        elif kind == "token_usage_record":
            yield from self._usage_events(entry, payload, when, model)

    def _response_item_events(
        self, entry: dict, payload: dict, when: datetime | None, model: str | None = None
    ) -> Iterator[TranscriptEvent]:
        """A message or a tool call. Every other item kind is skipped.

        `reasoning` is skipped for the reason `_message_text` drops thinking
        blocks on the other adapter: its `encrypted_content` is not text anyone
        saw, and a consumer matching a phrase would be reading the model's
        scratchpad as though it had been said.
        """
        kind = payload.get("type")
        if kind == "message":
            role = payload.get("role")
            if not isinstance(role, str) or role not in _MESSAGE_ROLES:
                return
            text = _rollout_text(payload.get("content"))
            if text:
                yield TranscriptEvent(
                    signal=Signal.MESSAGES,
                    timestamp=when,
                    role=role,
                    text=text,
                    model=model,
                    raw=entry,
                )
            return

        if not isinstance(kind, str) or kind not in _TOOL_CALL_KINDS:
            return
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            return
        use_id = payload.get("call_id")
        yield TranscriptEvent(
            signal=Signal.TOOL_CALLS,
            timestamp=when,
            # The same normalisation `parse_hook_input` performs, through the
            # same method: a transcript tool call and a `PreToolUse` tool call
            # are one concept, and two mappings would drift.
            tool=self._parse_tool({"tool_name": name, "tool_input": _tool_input(kind, payload)}),
            tool_use_id=use_id if isinstance(use_id, str) else None,
            model=model,
            raw=entry,
        )

    def _usage_events(
        self, entry: dict, payload: dict, when: datetime | None, model: str | None = None
    ) -> Iterator[TranscriptEvent]:
        """`usage` — this turn's accounting — and not the two running totals.

        The record carries three sibling objects of identical shape: `usage` and
        `turn_token_usage`, which were equal in every line measured, and
        `thread_token_usage`, the session-to-date total. `TokenUsage` is
        per-turn by its own docstring, so the cumulative one is not a candidate;
        between the two per-turn spellings, `usage` is the one the other
        adapters' field is named after.

        Codex's `cached_input_tokens` and `cache_write_input_tokens` are the
        read and creation halves `TokenUsage` names; `reasoning_output_tokens`
        and `total_tokens` have no field and are not folded into one, since a
        sum that silently includes reasoning is worse than an absent counter.

        `input_tokens` is *inclusive* of the cached half here, where
        `TokenUsage.input_tokens` is the input charged at full rate (ADR-066),
        so the cached half is subtracted back out. Measured over 92 rollouts
        and 5893 usage records: `total_tokens == input_tokens + output_tokens`
        on every one, and `cached_input_tokens` never exceeded `input_tokens`.
        Passing the provider's number through counted the cached tokens twice
        — once at the input rate and once at the read rate — and overstated
        fresh input 41x on the measured corpus. The clamp is for a record the
        corpus never produced: a negative charged input is worse than a zero.

        `response_id` is the dedup key and `turn_id` is not: measured over 176
        records, `response_id` was a string on every one and unique across all
        15 rollouts, while those same 176 shared 21 `turn_id`s — deduping on the
        turn would drop every usage record in a turn but the first. Nothing in
        the `response_item` stream carries it either (0 of 176 matched an item's
        `id`), so the record is not joined to that stream and stands alone.

        Codex reports one undifferentiated cache write, so
        `cache_creation_1h_tokens` stays `None`: a TTL split this provider does
        not disclose is not the same fact as a turn that wrote no 1-hour cache.
        """
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        response_id = payload.get("response_id")
        yield TranscriptEvent(
            signal=Signal.TOKEN_USAGE,
            timestamp=when,
            usage=TokenUsage(
                input_tokens=_charged_input(usage),
                output_tokens=_as_int(usage.get("output_tokens")),
                cache_read_tokens=_as_int(usage.get("cached_input_tokens")),
                cache_creation_tokens=_as_int(usage.get("cache_write_input_tokens")),
            ),
            model=model,
            message_id=response_id if isinstance(response_id, str) and response_id else None,
            raw=entry,
        )
