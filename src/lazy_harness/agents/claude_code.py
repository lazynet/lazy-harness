"""Claude Code agent adapter."""

from __future__ import annotations

import json
import os
import shlex
import shutil
from collections.abc import Collection, Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath

from lazy_harness import __version__
from lazy_harness.agents.base import (
    Bypass,
    ConfigArtifact,
    FileEdit,
    GoalStatus,
    HeadlessResult,
    HookDecision,
    HookEntry,
    HookEvent,
    HookOutput,
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

# Passing `--allowedTools ""` is a no-op: the CLI still grants its default read
# tools. Denying them by name is what actually pins a call to a single turn.
NO_TOOLS: tuple[str, ...] = (
    "Task",
    "Bash",
    "Glob",
    "Grep",
    "Read",
    "Edit",
    "Write",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
)

_TIER_MODELS: dict[str, str] = {
    "fast": "haiku",
    "balanced": "sonnet",
    "deep": "opus",
}


def _as_int(*candidates: object) -> int | None:
    """First candidate that is a real int. Unlike `or`, a legitimate 0 wins."""
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _cache_creation_split(usage: dict) -> tuple[int | None, int | None]:
    """A usage block's cache writes as (5-minute, 1-hour) tokens.

    **The breakdown wins where the two disagree.** Claude Code reports the
    total under `cache_creation_input_tokens` and the split under
    `cache_creation`, and across 102,464 measured usage records four of them
    disagree, by +2,640 tokens. `collector.split_cache_creation` resolves that
    in favour of the breakdown; this makes the same choice, because the two
    paths price the same turn and a second rule would bill it twice over.
    `tests/unit/test_transcript_reader_parity.py` asserts they agree, which is
    what keeps one answer in two places from becoming two answers.

    A transcript written before the breakdown existed carries only the total.
    Nothing records its TTL, so it goes to the 5-minute bucket and the 1-hour
    one stays `None` — absent, not zero, for the reason `TokenUsage`'s own
    docstring gives. The hand parser answers 0 there because it is summing
    ints on the way to a price; the arithmetic agrees, the claim does not.
    """
    breakdown = usage.get("cache_creation")
    if isinstance(breakdown, dict):
        return (
            _as_int(breakdown.get("ephemeral_5m_input_tokens")),
            _as_int(breakdown.get("ephemeral_1h_input_tokens")),
        )
    return _as_int(usage.get("cache_creation_input_tokens")), None


# Canonical event name -> how Claude Code delivers it. The single place the
# native casing lives; `supported_hooks()` and `_generate_hook_config()` both
# read it rather than repeating the mapping.
#
# `verdicts` is deliberately gated on evidence from this repository, not on
# what the vendor documentation names. Only two verdicts have been exercised
# here: `pre_tool_use_security` refuses with stderr + exit 2 at `pre_tool_use`,
# and `stop_verify_guard` emits `{"decision": "block"}` at `session_stop`. An
# empty set says "no verdict observed", which makes deploy refuse a blocking
# hook on that event — the safe direction. Add to a set when a verdict is
# actually observed being honoured, not when a doc claims it.
_HOOK_EVENTS: dict[str, HookSupport] = {
    "session_start": HookSupport("SessionStart"),
    "session_stop": HookSupport("Stop", frozenset({Verdict.BLOCK})),
    "session_end": HookSupport("SessionEnd"),
    "pre_compact": HookSupport("PreCompact"),
    "post_compact": HookSupport("PostCompact"),
    "pre_tool_use": HookSupport("PreToolUse", frozenset({Verdict.DENY})),
    "post_tool_use": HookSupport("PostToolUse"),
    "notification": HookSupport("Notification"),
    "user_prompt_submit": HookSupport("UserPromptSubmit"),
    "permission_request": HookSupport("PermissionRequest"),
}

# Native tool name -> the operation a builtin reasons about. A tool absent here
# parses with `operation=None`: known to have run, but not something any hook
# has been written to guard.
_TOOL_OPERATIONS: dict[str, Operation] = {
    "Bash": Operation.RUN_COMMAND,
    "Read": Operation.READ_FILE,
    "Edit": Operation.MODIFY_FILE,
    "Write": Operation.MODIFY_FILE,
    "NotebookEdit": Operation.MODIFY_FILE,
}

# Claude Code names the file differently per tool; both spellings are one path.
_FILE_PATH_KEYS: tuple[str, ...] = ("file_path", "notebook_path")

# Transcript entry types that carry a turn. Everything else Claude Code writes
# into the JSONL — `mode`, `ai-title`, `worktree-state`, `file-history-delta`
# and a dozen more — is UI bookkeeping no signal is defined over.
_TURN_TYPES: frozenset[str] = frozenset({"user", "assistant"})


def _iso_timestamp(value: object) -> datetime | None:
    """`timestamp` as a datetime, or None for anything that is not one.

    Never raises: a transcript written by a future release is allowed to change
    this field, and losing the time of one entry must not lose the entry.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _message_text(content: object) -> str:
    """The turn's text, with every non-text block dropped.

    `content` is a bare string on most user turns and a list of typed blocks on
    assistant turns. Thinking, tool_use and tool_result blocks are not text and
    are not joined in: a consumer counting words or matching a phrase would
    otherwise be reading the model's scratchpad as though the user had seen it.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


# --- Claude Code config documents (ConfigPlanner) ---

_SETTINGS_FILE = "settings.json"

# The launcher invocation every generated builtin command takes: `<binary> hook
# <name>`. Ownership is that canonical hook name, never the text of the command
# as a whole — flags the harness adds later (`--profile <name>`) change the text
# of every entry, and a classifier keyed on text reads its own previous output
# as another tool's hook and preserves it beside the new one.
_HOOK_SUBCOMMAND = "hook"

# Written by harness versions before the launcher existed, when a generated
# command was `{sys.executable} {path-under-builtins}`. Still recognised so a
# redeploy prunes those entries instead of preserving them as foreign.
_LEGACY_BUILTIN_MARKER = "lazy_harness/hooks/builtins/"


def _as_document(raw: str | None) -> dict:
    """The parsed document, or an empty one when it is missing or unusable.

    A file that is not JSON, or is JSON that is not an object, is treated as
    absent rather than as an error: refusing to deploy over a settings file some
    other tool corrupted would leave the profile with no hooks at all.
    """
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _entry_commands(entry: dict) -> list[str]:
    """Command strings carried by a single settings.json hook entry."""
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return []
    commands: list[str] = []
    for hook in hooks:
        if isinstance(hook, dict):
            command = hook.get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


def _is_harness_owned(command: str, *, binaries: Collection[str]) -> bool:
    """Whether the harness generated this command.

    `binaries` is what `_owned_binaries` reads off the artifact being merged, not
    off the live config: a config cannot answer "did I write this" — only the
    artifact can. A `hook` subcommand alone is deliberately not enough to claim a
    command, or another tool modelling hooks the same way would be adopted and
    then pruned.
    """
    normalised = command.replace("\\", "/")
    if _LEGACY_BUILTIN_MARKER in normalised:
        return True
    try:
        argv = shlex.split(normalised)
    except ValueError:
        return False
    if len(argv) < 3:
        return False
    if PurePosixPath(argv[0]).name not in binaries:
        return False
    if argv[1] != _HOOK_SUBCOMMAND:
        return False
    return not argv[2].startswith("-")


def _normalize_entry(entry: dict) -> tuple[dict, list[str]]:
    """Coerce a foreign hook entry into the schema Claude Code accepts.

    Returns the repaired entry and a description of each repair. A non-string
    matcher is the one seen in the wild: an installer writing `null` for "no
    matcher" makes Claude Code reject the entire settings file, which silently
    disables every unrelated hook in the profile.
    """
    repairs: list[str] = []
    fixed = dict(entry)
    matcher = fixed.get("matcher")
    if matcher is None:
        fixed["matcher"] = ""
        repairs.append('matcher: null -> ""')
    elif not isinstance(matcher, str):
        fixed["matcher"] = ""
        repairs.append(f'matcher: {type(matcher).__name__} -> ""')
    return fixed, repairs


def _owned_binaries(settings: dict, binary: str) -> set[str]:
    """The launchers whose commands this settings file may legitimately carry.

    Three sources, none of them the live config: the launcher the file records as
    having written it, so entries survive their binary being retired from every
    profile; the launcher this deploy is writing, so a first deploy onto a file
    that records nothing still recognises what it is about to generate; and the
    default, which is what every settings.json written before the stamp existed
    necessarily used. The set stays closed — a launcher nobody ever deployed is
    never claimed.
    """
    # Both imports are deferred: `agents.registry` imports this module, and
    # `core.artifact_version` imports `agents.registry`. At module level either
    # one closes the cycle.
    from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY
    from lazy_harness.core.artifact_version import extract_binary_from_settings

    owned = {DEFAULT_HARNESS_BINARY, binary}
    recorded = extract_binary_from_settings(settings)
    if recorded:
        owned.add(recorded)
    return owned


def _merge_hook_blocks(
    existing: object, generated: dict, *, binaries: Collection[str]
) -> tuple[dict, list[str], list[str], list[str]]:
    """Merge harness-generated hooks over an existing settings.json hooks block.

    Harness-owned entries are replaced by the freshly generated ones; everything
    else belongs to another tool and is carried through, repaired if its schema
    would make Claude Code reject the file. Events the harness does not model are
    passed through untouched rather than dropped.

    Returns the merged block and the three `WriteOp` diagnostics: preserved,
    repaired, and the harness entries this run no longer generates.
    """
    merged: dict = {event: list(entries) for event, entries in generated.items()}
    preserved: list[str] = []
    repaired: list[str] = []
    dropped: list[str] = []
    if not isinstance(existing, dict):
        return merged, preserved, repaired, dropped

    generated_commands = {
        command
        for entries in generated.values()
        for entry in entries
        if isinstance(entry, dict)
        for command in _entry_commands(entry)
    }

    for event, entries in existing.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            commands = _entry_commands(entry)
            if not commands:
                continue
            if all(_is_harness_owned(command, binaries=binaries) for command in commands):
                # Ours, and the merged block already carries whatever replaces
                # it. A command we no longer generate is being pruned, which is
                # the one thing this loop does that the user cannot otherwise see.
                dropped.extend(
                    f"{event}: {command}"
                    for command in commands
                    if command not in generated_commands
                )
                continue
            # Already emitted this run — the tool's own installer wrote it and
            # config declares it too. Keeping both would run the hook twice.
            if all(command in generated_commands for command in commands):
                continue
            fixed, fixes = _normalize_entry(entry)
            repaired.extend(f"{event}: {fix} ({commands[0]})" for fix in fixes)
            merged.setdefault(event, []).append(fixed)
            preserved.append(f"{event}: {commands[0]}")

    return merged, preserved, repaired, dropped


def _interpreter_is_present(candidate: Path) -> bool:
    """False for a script whose `#!` line names an interpreter that is not there.

    `execve` reports a missing interpreter as `ENOENT` against the *script*, so
    a launcher that trusted such a candidate raises `FileNotFoundError` naming a
    file that plainly exists — which is what `lh run` did on both Claude
    profiles after a stray fixture, shebanged into a git worktree's venv, won
    the mtime comparison and then outlived that worktree.

    A genuine build is a compiled executable with no shebang and is accepted
    without touching the filesystem twice. `#!/usr/bin/env python3` is judged on
    `env`, not on what `env` would go on to find: resolving that needs the
    interpreter's own PATH lookup, and a launcher is not the place to guess it.
    """
    try:
        with candidate.open("rb") as handle:
            if handle.read(2) != b"#!":
                return True
            shebang = handle.readline(4096).decode("utf-8", "replace")
    except OSError:
        return False
    interpreter = shebang.split(maxsplit=1)
    if not interpreter:
        return False
    return Path(interpreter[0]).exists()


class ClaudeCodeAdapter:
    """Adapter for Claude Code (Anthropic's CLI agent)."""

    @property
    def name(self) -> str:
        return "claude-code"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def skill_root(self, profile_config_dir: str) -> Path | None:
        return self.config_dir(profile_config_dir) / "skills"

    def env_var(self) -> str:
        return "CLAUDE_CONFIG_DIR"

    def resolve_binary(self) -> Path | None:
        """Locate the claude binary.

        Preference order:
          1. ~/.local/share/claude/versions/<newest mtime> — Claude Code's
             version-manager dir, picks the most recently installed build.
          2. shutil.which('claude'), unfiltered.

        Step 1 is the whole recursion guard, and step 2 carries an accepted
        risk: `lh run` exec's what this returns, so a PATH `claude` that is a
        wrapper calling `lh run` would fork-bomb. Nothing rejects it. Keying a
        filter on the `lh` entrypoint directory is what the guard cannot be —
        `uv tool install` puts `lh` and `claude` in the same `~/.local/bin`,
        so it would reject the genuine binary and leave `lh run` with
        `LaunchError("binary-not-found")` on every machine without a
        version-manager dir. The risk stays open because it needs that dir to
        be absent *and* a wrapper on PATH; a shell alias or function, which is
        how re-entry is normally spelled, is invisible to `shutil.which`.
        Both halves are pinned in `tests/unit/test_agent_claude.py`.
        """
        versions_dir = Path.home() / ".local" / "share" / "claude" / "versions"
        if versions_dir.is_dir():
            candidates = [
                p
                for p in versions_dir.iterdir()
                if p.is_file() and os.access(p, os.X_OK) and _interpreter_is_present(p)
            ]
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime)
        which = shutil.which("claude")
        if which:
            return Path(which)
        return None

    def supported_hooks(self) -> list[str]:
        return list(_HOOK_EVENTS)

    def hook_events(self) -> dict[str, HookSupport]:
        return dict(_HOOK_EVENTS)

    def _generate_hook_config(self, hooks: dict[str, list[str | HookEntry]]) -> dict:
        """Generate Claude Code settings.json hooks section.

        Each value can be a plain command string (uses the event's default
        matcher) or a `HookEntry` (overrides the matcher per-script).
        """
        matcher_map = {
            "pre_tool_use": "Bash",
            "post_tool_use": "Edit|Write",
        }
        settings_hooks: dict[str, list[dict]] = {}
        for event, scripts in hooks.items():
            support = _HOOK_EVENTS.get(event)
            if support is None:
                continue
            cc_event = support.native_name
            default_matcher = matcher_map.get(event, "")
            matchers = []
            for script in scripts:
                if isinstance(script, HookEntry):
                    command = script.command
                    matcher = script.matcher or default_matcher
                else:
                    command = script
                    matcher = default_matcher
                matchers.append(
                    {
                        "matcher": matcher,
                        "hooks": [{"type": "command", "command": command}],
                    }
                )
            settings_hooks[cc_event] = matchers
        return settings_hooks

    # --- the canonical hook contract (ADR-041) ---
    #
    # Claude Code is the agent the contract was extracted from, so both of these
    # are pass-throughs: no field is renamed and no value is reinterpreted. They
    # exist so that the builtins stop reading `tool_input["file_path"]` directly
    # and a second agent has somewhere to differ.

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        # The three string fields are read with `isinstance` rather than `str()`
        # because `str()` on a list or an int yields something that *looks* like
        # a session id or a path and is not one. These are what the hooks key
        # their metrics, their memory scope and their transcript reads on, so a
        # malformed value has to arrive as absent, not as plausible.
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
            stop_hook_active=bool(payload.get("stop_hook_active", False)),
            message=payload.get("message"),
            raw=payload,
        )

    @staticmethod
    def _parse_tool(payload: dict) -> ToolCall | None:
        name = payload.get("tool_name")
        if not name:
            return None
        args = payload.get("tool_input")
        if not isinstance(args, dict):
            args = {}
        operation = _TOOL_OPERATIONS.get(str(name))
        path = next((args[k] for k in _FILE_PATH_KEYS if args.get(k)), None)
        edits: tuple[FileEdit, ...] = ()
        reads: tuple[Path, ...] = ()
        if operation is Operation.READ_FILE and path:
            reads = (Path(str(path)),)
        elif operation is Operation.MODIFY_FILE and path:
            content = args.get("content")
            old, new = args.get("old_string"), args.get("new_string")
            edits = (
                FileEdit(
                    path=Path(str(path)),
                    # Left False for every Claude Code tool. `Write` creates or
                    # overwrites and the payload does not say which, so claiming
                    # a create would make an overwrite of an existing file read
                    # as a new one. The field is for agents that disclose it.
                    content=str(content) if content is not None else None,
                    # An absent `new_string` is a deletion, matching what
                    # `pre_tool_use_memory_size` projects today. `str(None)`
                    # would project the literal text "None" into the file.
                    replacements=((str(old), "" if new is None else str(new)),)
                    if old is not None
                    else (),
                    replace_all=bool(args.get("replace_all", False)),
                ),
            )
        command = args.get("command")
        return ToolCall(
            native_name=str(name),
            operation=operation,
            command=str(command) if command is not None else None,
            reads=reads,
            offset=_as_int(args.get("offset")),
            limit=_as_int(args.get("limit")),
            edits=edits,
            raw_input=args,
        )

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        support = _HOOK_EVENTS.get(event.event)
        verdict = decision.verdict
        if verdict is not None and (support is None or verdict not in support.verdicts):
            raise ValueError(
                f"claude-code does not honour {verdict.value!r} on {event.event!r}; "
                f"honoured here: {sorted(v.value for v in support.verdicts) if support else []}"
            )
        # PreCompact is a text channel, not a JSON one. Claude Code's
        # `hookSpecificOutput` union has no PreCompact variant (recorded
        # against the 2.1.234 binary in `hooks/builtins/pre_compact.py` and in
        # ADR-036 D2): a JSON payload there fails schema validation, which
        # marks the hook failed and discards its output. The executor joins
        # each *successful* hook's raw stdout into `newCustomInstructions`, so
        # the summary arrives as the bytes the hook wrote or not at all.
        #
        # The verdict needs no second check: `_HOOK_EVENTS["pre_compact"]`
        # declares no verdicts, so every verdict is already refused above. The
        # only narrowing left to name is the three channels raw text cannot
        # express. Refusing beats dropping them -- a decision asking for a
        # system message here would otherwise get silence and a zero exit,
        # which reads as success.
        if event.event == "pre_compact":
            unsupported = [
                channel
                for channel, requested in (
                    ("system_message", bool(decision.system_message)),
                    ("stop", decision.stop),
                    ("suppress_output", decision.suppress_output),
                )
                if requested
            ]
            if unsupported:
                raise ValueError(
                    "claude-code's PreCompact channel is plain text and cannot carry "
                    + ", ".join(unsupported)
                )
            # The trailing newline is appended here for the same reason as on
            # the JSON path below -- the adapter owns the bytes. `pre_compact`
            # emits `print(...)` today, so a migrated hook that returned the
            # summary unchanged would differ from the shipped one by exactly
            # one character that nothing else would account for.
            return HookOutput(
                stdout=f"{decision.additional_context}\n" if decision.additional_context else None,
                stderr="",
                exit_code=0,
            )
        body: dict[str, object] = {}
        if verdict is Verdict.BLOCK:
            body["decision"] = "block"
            body["reason"] = decision.reason
        elif verdict in (Verdict.ALLOW, Verdict.ASK):
            body["hookSpecificOutput"] = {
                "hookEventName": support.native_name if support else event.event,
                "permissionDecision": verdict.value,
                "permissionDecisionReason": decision.reason,
            }
        if decision.additional_context:
            nested = body.setdefault("hookSpecificOutput", {})
            assert isinstance(nested, dict)
            nested.setdefault("hookEventName", support.native_name if support else event.event)
            nested["additionalContext"] = decision.additional_context
        # Top level, never nested. `hookSpecificOutput` accepts exactly
        # additionalContext, permissionDecision, permissionDecisionReason and
        # updatedInput (verified against the 2.1.269 binary) and discards the
        # rest, so a nested systemMessage parses and displays nothing.
        if decision.system_message:
            body["systemMessage"] = decision.system_message
        if decision.stop:
            body["continue"] = False
            if decision.reason and verdict is not Verdict.BLOCK:
                body["stopReason"] = decision.reason
        if decision.suppress_output:
            body["suppressOutput"] = True
        # The trailing newline is part of the bytes, not decoration. Every hook
        # emitted `print(json.dumps(...))` before the runner, and the design
        # puts serialisation in exactly one place so that stays reproducible;
        # without it here the byte goldens differ from the shipped hooks by a
        # single character that nothing else would ever account for.
        stdout = json.dumps(body) + "\n" if body else None
        # Exit 2 is the only channel that actually refuses a tool call, and the
        # message the user reads is the stderr text rather than the JSON. The
        # JSON still travels: Claude Code reads valid stdout whether or not the
        # hook exited 2, so returning early here would silently drop a system
        # message the agent would have shown.
        if verdict is Verdict.DENY:
            return HookOutput(stdout=stdout, stderr=decision.reason, exit_code=2)
        return HookOutput(stdout=stdout, stderr="", exit_code=0)

    def global_config_link(self) -> Path | None:
        return Path.home() / ".claude"

    def mcp_config_file(self) -> str:
        return ".claude.json"

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "projects", "logs": "logs", "queue": "queue"}

    def credentials_file(self) -> str | None:
        """`.credentials.json`, whose freshness is platform-dependent.

        On Linux it is the store. On macOS the live credential is in the
        keychain and this file is a mirror nothing re-synchronises — measured on
        2026-09-16, a profile logged in that morning still carried a file from
        eight days earlier with an expired refresh token. The name is still
        correct on both; what differs is how much a reader may conclude from it,
        which is the preflight's call to make and not this one's (ADR-045 D6).
        """
        return ".credentials.json"

    def system_docs(self) -> list[Path]:
        """Claude Code reads `CLAUDE.md` and nothing else — one destination."""
        return [Path("CLAUDE.md")]

    def bypass_argv(self, level: Bypass) -> list[str] | None:
        """Two of the three, verified against `claude --help` on 1.x.

        ENABLE is the flag `lcca` ships today, and its help text is the reason
        it is ENABLE rather than ACTIVATE: "Enable bypassing all permission
        checks **as an option, without it being enabled by default**". The
        migration to `lh run --bypass=enable` therefore preserves the alias's
        semantics exactly, which is the whole point of preserving it.

        NO_SANDBOX is `None`. Claude Code exposes no OS-sandbox switch on its
        argv at all — the sandboxing it does is a property of where it is run,
        not a flag — so there is nothing to return that would not be a lie.
        Answering with the ACTIVATE flag would turn "remove the sandbox" into
        "remove the prompts", which is a different and unrequested launch.
        """
        if level is Bypass.ENABLE:
            return ["--allow-dangerously-skip-permissions"]
        if level is Bypass.ACTIVATE:
            return ["--dangerously-skip-permissions"]
        return None

    def process_name(self) -> str:
        return "claude"

    # --- transcript reading (TranscriptReader) ---
    #
    # A move of code that already existed rather than new capability: five hooks
    # and fifteen other modules parse this same JSONL by hand today. The design
    # puts Claude Code's reader at step 2 precisely so decision 11 does not
    # undeploy working hooks for the length of the migration.

    def signals(self) -> set[Signal]:
        """All four. Claude Code is where the vocabulary was derived from."""
        return {Signal.MESSAGES, Signal.TOOL_CALLS, Signal.TOKEN_USAGE, Signal.GOAL_STATUS}

    def locate_sessions(self, config_dir: Path, since: datetime | None) -> Iterator[Path]:
        """`<config_dir>/projects/**/*.jsonl`, filtered by modification time.

        Order is the filesystem's and is not promised: a caller that needs one
        sorts. Yielding as the walk proceeds is what keeps a config dir holding
        thousands of sessions from being materialised to answer "any since
        Monday".
        """
        root = config_dir / (self.session_dirs()["sessions"] or "projects")
        cutoff = since.timestamp() if since is not None else None
        try:
            candidates = root.glob("**/*.jsonl")
            for path in candidates:
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

    def read(self, path: Path) -> Iterator[TranscriptEvent]:
        """One transcript, line by line, yielding only what a signal is defined over.

        Lazy on purpose, and the laziness is load-bearing twice. `read()` opens
        nothing until the first `next()`, so a hook that builds its reader when
        it starts still judges the transcript as of the moment it decides. And
        a consumer looking for one marker — `stop_verify_guard` looking for a
        goal — stops at the first hit instead of parsing a session that can run
        to hundreds of megabytes.

        `errors="replace"` rather than a strict decode: one byte the agent
        failed to write cleanly would otherwise raise mid-iteration and cost
        every line after it, which on this hook reads as "no goal was declared".
        """
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            return
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
                if isinstance(entry, dict):
                    yield from self._events_from(entry)

    def _events_from(self, entry: dict) -> Iterator[TranscriptEvent]:
        """Every event one transcript line carries — there can be several.

        An assistant turn with text, two tool calls and a usage record is one
        line and four events, which is why the unit is the signal occurrence.
        """
        when = _iso_timestamp(entry.get("timestamp"))
        kind = entry.get("type")

        if kind == "attachment":
            attachment = entry.get("attachment")
            if not isinstance(attachment, dict) or attachment.get("type") != "goal_status":
                return
            condition = attachment.get("condition")
            met = attachment.get("met")
            yield TranscriptEvent(
                signal=Signal.GOAL_STATUS,
                timestamp=when,
                goal=GoalStatus(
                    condition=condition if isinstance(condition, str) else None,
                    # `isinstance(met, bool)` and not `bool(met)`: an absent
                    # flag must arrive absent, not as "the goal is not met".
                    met=met if isinstance(met, bool) else None,
                ),
                raw=entry,
            )
            return

        # `isinstance` before the membership test, not just for tidiness: a
        # `"type"` of `[]` or `{}` is valid JSON, and `in` hashes its left
        # operand, so the lookup alone raises `TypeError` out of this generator
        # and ends the read. Skipping the entry costs one line; raising costs
        # every line after it.
        if not isinstance(kind, str) or kind not in _TURN_TYPES:
            return
        message = entry.get("message")
        if not isinstance(message, dict):
            return

        role = message.get("role")
        if not isinstance(role, str) or not role:
            role = str(kind)
        content = message.get("content")

        # Both belong to the line, not to one signal on it: the model that
        # produced a turn also produced the tool calls in it, and a consumer
        # attributing either has the same answer. Read once, carried on every
        # event this line yields.
        model = message.get("model")
        model = model if isinstance(model, str) and model else None
        message_id = message.get("id")
        message_id = message_id if isinstance(message_id, str) and message_id else None

        text = _message_text(content)
        if text:
            # A turn built entirely of tool_use blocks is not a message: it
            # yields its tool calls below and nothing here, so a consumer
            # counting turns does not count empty ones.
            yield TranscriptEvent(
                signal=Signal.MESSAGES,
                timestamp=when,
                role=role,
                text=text,
                model=model,
                message_id=message_id,
                raw=entry,
            )

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                if not isinstance(name, str) or not name:
                    continue
                use_id = block.get("id")
                yield TranscriptEvent(
                    signal=Signal.TOOL_CALLS,
                    timestamp=when,
                    role=role,
                    # The same normalisation `parse_hook_input` performs, in
                    # the same place: a transcript tool call and a PreToolUse
                    # tool call are one concept, and two mappings would drift.
                    tool=self._parse_tool({"tool_name": name, "tool_input": block.get("input")}),
                    tool_use_id=use_id if isinstance(use_id, str) else None,
                    model=model,
                    message_id=message_id,
                    raw=entry,
                )

        usage = message.get("usage")
        if isinstance(usage, dict):
            cache_5m, cache_1h = _cache_creation_split(usage)
            yield TranscriptEvent(
                signal=Signal.TOKEN_USAGE,
                timestamp=when,
                role=role,
                usage=TokenUsage(
                    input_tokens=_as_int(usage.get("input_tokens")),
                    output_tokens=_as_int(usage.get("output_tokens")),
                    cache_read_tokens=_as_int(usage.get("cache_read_input_tokens")),
                    # Siblings, not a total and a share of it: the two are
                    # priced at different rates, and a consumer that wants the
                    # whole write adds them.
                    cache_creation_tokens=cache_5m,
                    cache_creation_1h_tokens=cache_1h,
                ),
                model=model,
                message_id=message_id,
                raw=entry,
            )

    # --- session identity (TranscriptIdentity) ---

    def session_identity(self, path: Path) -> SessionIdentity:
        """Read off the path: Claude Code encodes both facts in it.

        A transcript lives at `<sessions>/<encoded project>/<session>.jsonl`,
        and a subagent's at `<encoded project>/<session>/subagents/**.jsonl`.
        Subagent turns bill to the session that spawned them — attributing them
        to their own file would turn every spawn into a session row of its own
        and understate exactly the runs that did the most work.

        The project directory is found by its *parent* being the sessions
        directory this adapter declares, not by counting components: a
        subagent transcript sits two levels deeper than a plain one, and a
        fixed index would read the session id as the project on one of them.
        """
        # Local import: `monitoring` imports this package, so naming it at
        # module scope would close an import cycle.
        from lazy_harness.monitoring.collector import extract_project_name

        parts = path.parts
        session_id = path.stem
        if "subagents" in parts[:-1]:
            index = parts.index("subagents")
            if index >= 1:
                session_id = parts[index - 1]

        project: str | None = None
        sessions_dir = self.session_dirs().get("sessions") or "projects"
        for ancestor in path.parents:
            if ancestor.parent.name == sessions_dir:
                project = extract_project_name(ancestor.name)
                break
        return SessionIdentity(session_id=session_id, project=project)

    # --- headless invocation (HeadlessAgent) ---

    def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
        """Map a tier to a CLI alias. An explicit id wins and is not validated."""
        if explicit:
            return explicit
        if tier is None:
            return None
        try:
            return _TIER_MODELS[tier]
        except KeyError:
            known = ", ".join(sorted(_TIER_MODELS))
            raise ValueError(f"unknown tier {tier!r} for claude-code (known: {known})") from None

    def headless_argv(self, *, model: str | None, allowed_tools: list[str] | None) -> list[str]:
        argv = ["-p", "--output-format", "json"]
        if model:
            argv += ["--model", model]
        if allowed_tools:
            argv += ["--allowedTools", ",".join(allowed_tools)]
        elif allowed_tools is not None:
            argv += ["--disallowedTools", ",".join(NO_TOOLS)]
        return argv

    def session_argv(self, session_id: str) -> list[str]:
        """Pin the conversation. A session id already in use is refused, not
        resumed: exit 1 with an empty stdout, so the caller must never reuse
        one."""
        return ["--session-id", session_id]

    def parse_headless_result(self, stdout: str, exit_code: int) -> HeadlessResult:
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            data = None
        if not isinstance(data, dict):
            return HeadlessResult(
                success=exit_code == 0,
                output=stdout,
                exit_code=exit_code,
                raw=None,
            )

        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        uncached = _as_int(usage.get("input_tokens"), data.get("input_tokens"))
        cache_creation = _as_int(usage.get("cache_creation_input_tokens"))
        cache_read = _as_int(usage.get("cache_read_input_tokens"))
        # `input_tokens` is only the uncached slice of the last turn — it reads
        # as single digits even on a 100k-token prompt. The input is the sum.
        prompt_tokens = (
            None
            if uncached is None and cache_creation is None and cache_read is None
            else (uncached or 0) + (cache_creation or 0) + (cache_read or 0)
        )

        # Claude Code's own figure, passed through verbatim — the harness
        # never recomputes it. It can disagree with `lh metrics` costs: as of
        # 2026-08-31 it bills claude-sonnet-5 at claude-sonnet-4-6's rates
        # ($3/$15 rather than $2/$10), over-reporting those sessions by 50%.
        # Recomputing it here would make the two agree by construction and
        # cost us the only signal we get when it is our own table that has
        # gone stale, so the disagreement is deliberate.
        cost = data.get("total_cost_usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            cost = data.get("cost_usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            cost = None

        result_text = data.get("result")
        session_id = data.get("session_id")
        return HeadlessResult(
            success=exit_code == 0 and data.get("is_error") is not True,
            output=result_text if isinstance(result_text, str) else stdout,
            exit_code=exit_code,
            cost_usd=float(cost) if cost is not None else None,
            duration_ms=_as_int(data.get("duration_ms")),
            prompt_tokens=prompt_tokens,
            output_tokens=_as_int(usage.get("output_tokens"), data.get("output_tokens")),
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            num_turns=_as_int(data.get("num_turns")),
            raw=data,
            session_id=session_id if isinstance(session_id, str) else None,
        )

    def _generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        normalized: dict[str, dict] = {}
        for name, entry in servers.items():
            normalized[name] = {
                "command": entry["command"],
                "args": list(entry.get("args", [])),
            }
            if entry.get("env"):
                normalized[name]["env"] = dict(entry["env"])
        return {"mcpServers": normalized}

    # --- config planning (ConfigPlanner) ---
    #
    # Merging is an adapter operation; writing is the engine's (decision 4,
    # 2026-09-13 multi-agent design). Everything below parses and reserialises
    # Claude Code's own documents and returns final text — the engine never
    # learns what a `matcher` is.

    def config_targets(self) -> list[Path]:
        """Every file this adapter may read or write, relative to the config dir."""
        return [Path(_SETTINGS_FILE), Path(self.mcp_config_file())]

    def plan_config(
        self,
        hooks: dict[str, list[HookEntry]],
        servers: dict[str, dict],
        existing: dict[Path, str],
        *,
        binary: str | None = None,
    ) -> list[WriteOp]:
        """Plan both documents in one call.

        `binary` is the launcher this deploy writes into the generated commands,
        and it is keyword-only with a default because the design's signature does
        not carry it while `settings.json` does: the stamp naming the writing
        launcher is what stops the *next* deploy reading its own previous output
        as another tool's hooks. Deriving it from the commands would be wrong for
        a profile whose only hooks are third-party, which generates no launcher
        invocation to read it off.
        """
        from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY

        ops: list[WriteOp] = []
        settings_op = self._plan_settings(
            hooks,
            existing.get(Path(_SETTINGS_FILE)),
            binary=binary or DEFAULT_HARNESS_BINARY,
        )
        if settings_op is not None:
            ops.append(settings_op)
        mcp_op = self._plan_mcp(servers, existing.get(Path(self.mcp_config_file())))
        if mcp_op is not None:
            ops.append(mcp_op)
        return ops

    def _plan_settings(
        self, hooks: dict[str, list[HookEntry]], existing_raw: str | None, *, binary: str
    ) -> WriteOp | None:
        """Merge the generated hooks over an existing settings.json.

        Returns `None` when there is nothing to deploy. An empty plan is not the
        same as a plan to write an empty hooks block: the latter would uninstall
        every foreign entry on a profile that configures no harness hooks.
        """
        if not hooks:
            return None

        from lazy_harness.core.artifact_version import SETTINGS_BINARY_KEY

        widened: dict[str, list[str | HookEntry]] = {
            event: list(entries) for event, entries in hooks.items()
        }
        generated = self._generate_hook_config(widened)
        settings = _as_document(existing_raw)

        merged, preserved, repaired, dropped = _merge_hook_blocks(
            settings.get("hooks", {}),
            generated,
            binaries=_owned_binaries(settings, binary),
        )

        # Decision 9: the document declares the version and the launcher that
        # wrote it, at the top level rather than inside `hooks` — that block is a
        # `{event: [entry, ...]}` contract and a scalar there breaks every
        # generic reader of it, the harness's own included.
        settings["lh_version"] = __version__
        settings[SETTINGS_BINARY_KEY] = binary
        settings["hooks"] = merged

        return WriteOp(
            artifact=ConfigArtifact(
                relative_path=Path(_SETTINGS_FILE),
                content=json.dumps(settings, indent=2) + "\n",
            ),
            relative_path=Path(_SETTINGS_FILE),
            preserved=preserved,
            dropped=dropped,
            repaired=repaired,
        )

    def _plan_mcp(self, servers: dict[str, dict], existing_raw: str | None) -> WriteOp | None:
        """Merge the detected MCP servers into the agent's MCP config document."""
        if not servers:
            return None

        generated = self._generate_mcp_config(servers).get("mcpServers", {})
        document = _as_document(existing_raw)
        current = document.get("mcpServers")
        if not isinstance(current, dict):
            current = {}

        preserved = [f"mcpServers: {name}" for name in current if name not in generated]
        current.update(generated)
        document["mcpServers"] = current

        relative = Path(self.mcp_config_file())
        return WriteOp(
            artifact=ConfigArtifact(
                relative_path=relative,
                content=json.dumps(document, indent=2) + "\n",
            ),
            relative_path=relative,
            preserved=preserved,
        )
