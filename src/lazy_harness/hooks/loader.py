"""Hook discovery — resolve built-in and user hooks by name."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.agents.base import Operation, Signal
from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir


@dataclass(frozen=True)
class BuiltinHookSpec:
    """Registry entry for a builtin hook.

    `matcher` is an optional per-hook matcher override consumed by the agent
    adapter when generating native hook config (e.g. settings.json). Unset =
    the agent's event-level default applies.

    A plain string applies to every event the hook is wired to. A mapping keyed
    by `config.toml` event name lets one hook carry different matchers per
    event, which a hook wired to both tool and lifecycle events needs: `*` is
    correct for PostToolUse and meaningless on Stop.
    """

    module: str
    matcher: str | Mapping[str, str] | None = None
    event: str | None = None
    """Canonical event this hook is wired to, for a payload that does not say.

    `lh hook <name>` carries no event flag and `lh hooks run` hands the runner
    `{}`, so `hook_event_name` is not always there to read — and without an
    event the adapter can neither parse the payload nor name the event back in
    its output. For a hook that handles one event the answer is known without
    the payload — from `plugins/builtins.py` where the wiring is static, and
    from the hook itself where the operator places it. A hook that branches on
    several leaves this unset rather than naming one of them. A payload that
    *does* name an event still wins, and a name no adapter recognises is still
    a refusal rather than a fallback: that is a typo, not an absence.
    """

    blocking: bool = False
    """Whether this hook refuses actions, which decides its failure policy.

    A blocking hook that cannot run exits 2 rather than 0: exit 0 with no
    output is how a hook says "no objection", so degrading there would turn
    every crash of a guard into an approval. An informational hook degrades
    the other way, since refusing a tool call it was never meant to judge is
    worse than losing its output.
    """

    operations: frozenset[Operation] = frozenset()
    """Tool operations this hook reasons about (decision 9 of the design).

    Declared rather than left to the `matcher` regex, which names Claude Code's
    own tools: a hook installed on another agent with a translated matcher
    still has to be asked whether the operations it guards exist there. Empty
    means a hook that does not look at tool calls at all.
    """

    signals: frozenset[Signal] | Mapping[str, frozenset[Signal]] = frozenset()
    """Transcript signals this hook needs (decision 11 of the design).

    Declared before any `TranscriptReader` exists, which is the point: a
    boolean `requires_transcript` would re-enable `stop-verify-guard` the
    moment some reader shipped messages and tokens, and it would then find no
    `/goal` marker, conclude there is nothing to verify, and pass — a hook that
    cannot fail, reported green.

    A plain set applies to every event the hook is wired to, which is what all
    but one spec wants. A mapping keyed by `config.toml` event name declares per
    *placement*, for a hook whose placements read different things — the same
    widening `matcher` above carries, added for the same hook. An event the
    mapping omits needs nothing: `herdr-context-gauge` opens the transcript on
    three of its four placements and `herdr_context_gauge.py:175` short-circuits
    before `_tokens_of` on the fourth, so a flat `TOKEN_USAGE` would make deploy
    omit the retract too and strand a dead session's gauge on its pane.
    """

    migrated: bool = False
    """Whether this builtin's `main()` takes a `HookEvent` and returns a decision.

    TRANSITIONAL. The runner and the eighteen builtins cannot move in one
    commit, so both entry points route on this field: `True` goes through
    `hooks.runner.run_hook`, `False` through the pre-runner path that calls
    `main()` with no arguments and lets it own stdin, both channels and the
    exit code.

    Declared here rather than inferred from the module — a signature check
    would read the same today and lie the moment a migrated `main()` grows a
    default. Step 5 of
    `specs/designs/2026-09-13-multi-agent-harness-design.md` migrates the last
    builtin and deletes this field along with the branches that read it.
    """

    def matcher_for(self, event: str | None) -> str | None:
        if isinstance(self.matcher, Mapping):
            return self.matcher.get(event) if event else None
        return self.matcher

    def signals_for(self, event: str | None) -> frozenset[Signal]:
        """What this hook reads at one placement.

        A mapping that does not name the event declares nothing for it, and so
        does a mapping asked with no event at all — the union would be a guess
        at which placement the caller meant, and guessing high is what omits a
        working hook from a deploy. `matcher_for` resolves the same way.
        """
        if isinstance(self.signals, Mapping):
            return self.signals.get(event, frozenset()) if event else frozenset()
        return self.signals


@dataclass
class HookInfo:
    name: str
    path: Path
    is_builtin: bool
    matcher: str | None = None


_BUILTIN_HOOKS: dict[str, BuiltinHookSpec] = {
    "compound-loop": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.compound_loop",
        event="session_stop",
        migrated=True,
    ),
    "context-inject": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.context_inject",
        event="session_start",
        migrated=True,
    ),
    "engram-persist": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.engram_persist",
        event="session_stop",
        # No `signals`: this hook never opens the transcript. It takes the
        # declared path as a *name* — `resolve_project_dir` reads the parent
        # directory the agent encoded into it — and reads `decisions.jsonl` and
        # `failures.jsonl` beside it. Declaring one would make `deploy` refuse
        # to install it on an agent whose reader cannot supply a signal the
        # hook never touches.
        migrated=True,
    ),
    "herdr-context-gauge": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.herdr_context_gauge",
        matcher={"post_tool_use": "*"},
        # No `event`: this hook branches on the event it receives and is wired
        # to four, so no single fallback is right. A payload naming its own
        # event always wins over this field anyway (`runner._canonical_event`).
        #
        # `signals` is per placement because the placements disagree. Three
        # reach `_tokens_of` and need the window; `session_end` short-circuits
        # at `:175` and reads no transcript, because its whole job is retracting
        # a dead session's gauge. Declaring `TOKEN_USAGE` flat would omit the
        # retract on any agent lacking the signal and leave the gauge on the
        # pane forever, which is worse than not shipping the hook.
        signals={
            "post_tool_use": frozenset({Signal.TOKEN_USAGE}),
            "session_stop": frozenset({Signal.TOKEN_USAGE}),
            "session_start": frozenset({Signal.TOKEN_USAGE}),
        },
        migrated=True,
    ),
    "post-tool-use-ansible-lint": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.post_tool_use_ansible_lint",
        matcher="Edit|Write",
        event="post_tool_use",
        operations=frozenset({Operation.MODIFY_FILE}),
        # No `signals`: this hook reads the file the tool call edited and the
        # linter's own output, never the transcript. Declaring one would make
        # `deploy` refuse to install it on an agent whose reader cannot supply a
        # signal the hook never touches.
        migrated=True,
    ),
    "post-tool-use-format": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.post_tool_use_format",
        event="post_tool_use",
        operations=frozenset({Operation.MODIFY_FILE}),
        migrated=True,
    ),
    "post-tool-use-sync-claude": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.post_tool_use_sync_claude",
        matcher="Edit|Write",
        event="post_tool_use",
        operations=frozenset({Operation.MODIFY_FILE}),
        # No `signals`: this hook never opens the transcript. It reads the
        # edited path out of the tool call and the segment files off disk.
        # Declaring one would make `deploy` refuse to install it on an agent
        # whose reader cannot supply a signal the hook never touches.
        migrated=True,
    ),
    "pre-compact": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_compact",
        event="pre_compact",
        # No `signals`, and not because this hook never opens the transcript —
        # it does. `parse_transcript` reads `role` and `content` at the *top
        # level* of each JSONL line and Claude Code nests both under `message`,
        # so both loops have always yielded nothing (measured: zero top-level
        # `role` across 3215 production lines; `specs/backlog.md:125` owns the
        # repair). Declaring `MESSAGES` or `TOOL_CALLS` would name reads that do
        # not happen and let `deploy` omit the hook on an agent whose reader
        # lacks them — losing `build_memory_tails`, the part that works, over a
        # transcript read that does not.
        migrated=True,
    ),
    "pre-tool-use-git-scope": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_tool_use_git_scope",
        matcher="Bash",
        event="pre_tool_use",
        blocking=True,
        operations=frozenset({Operation.RUN_COMMAND}),
        # No `signals`: this hook reads the command string off the tool call and
        # the checkout's `.git` off the filesystem, never the transcript.
        # Declaring one would make `deploy` refuse to install a blocking guard
        # on an agent whose reader cannot supply a signal the hook never
        # touches — and an uninstalled guard is silent, not loud.
        migrated=True,
    ),
    "pre-tool-use-memory-size": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_tool_use_memory_size",
        matcher="Edit|Write",
        event="pre_tool_use",
        operations=frozenset({Operation.MODIFY_FILE}),
        # No signals: this hook reads the tool call and, for an `Edit`, the file
        # already on disk. It never opens a transcript, so declaring one would
        # make `deploy` omit a working warning on any agent whose reader cannot
        # supply a signal the hook never touches.
        migrated=True,
    ),
    "pre-tool-use-read-size": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_tool_use_read_size",
        matcher="Read",
        event="pre_tool_use",
        operations=frozenset({Operation.READ_FILE}),
        # No `signals`: this hook sizes the file the tool call names and reads
        # nothing else. It never opens a transcript, so declaring one would make
        # `deploy` omit a working warning on any agent whose reader cannot supply
        # a signal the hook does not touch.
        migrated=True,
    ),
    "pre-tool-use-security": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_tool_use_security",
        matcher="Bash|Read|Edit|Write|NotebookEdit",
        event="pre_tool_use",
        blocking=True,
        operations=frozenset({Operation.RUN_COMMAND, Operation.READ_FILE, Operation.MODIFY_FILE}),
        migrated=True,
    ),
    "session-start-preflight": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.session_start_preflight",
        event="session_start",
        # No signals: this hook reads a credentials file, a git remote and
        # `PATH`. It never opens a transcript, so declaring one would make
        # `deploy` omit a working preflight on any agent whose reader cannot
        # supply a signal it does not touch.
        migrated=True,
    ),
    "session-end": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.session_end",
        event="session_end",
        migrated=True,
    ),
    "session-export": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.session_export",
        event="session_stop",
        # The one lifecycle hook that reads message *text* in its own process
        # (`knowledge/session_export.py:43`). `session-end` and `compound-loop`
        # only locate a transcript and enqueue its path; their worker reads it
        # later, out of process, so declaring MESSAGES for them would make
        # `deploy` omit them on an agent whose reader never has to supply it.
        signals=frozenset({Signal.MESSAGES}),
        migrated=True,
    ),
    "stop-context-rotate": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.stop_context_rotate",
        event="session_stop",
        signals=frozenset({Signal.TOKEN_USAGE}),
        migrated=True,
    ),
    "stop-verify-guard": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.stop_verify_guard",
        event="session_stop",
        signals=frozenset({Signal.GOAL_STATUS}),
        migrated=True,
    ),
    "user-prompt-goal": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.user_prompt_goal",
        event="user_prompt_submit",
        # No `signals`: this hook reads `event.prompt` and nothing else. The
        # goal *verdict* it feeds -- `goal_declared`/`goal_absent` -- is graded
        # by the compound-loop worker from the transcript, out of process, so
        # declaring one here would make `deploy` omit a working sensor on any
        # agent whose reader cannot supply a signal the hook never touches.
        migrated=True,
    ),
}


def list_builtin_hooks() -> list[str]:
    return list(_BUILTIN_HOOKS.keys())


def _find_builtin(name: str, event: str | None = None) -> HookInfo | None:
    spec = _BUILTIN_HOOKS.get(name)
    if spec is None:
        return None
    parts = spec.module.split(".")
    base = Path(__file__).parent / "builtins" / f"{parts[-1]}.py"
    return HookInfo(
        name=name,
        path=base,
        is_builtin=True,
        matcher=spec.matcher_for(event),
    )


def _find_user_hook(name: str, user_hooks_dir: Path | None = None) -> HookInfo | None:
    hooks_dir = user_hooks_dir or config_dir() / "hooks"
    if not hooks_dir.is_dir():
        return None
    for candidate in [hooks_dir / f"{name}.py", hooks_dir / name]:
        if candidate.is_file():
            return HookInfo(name=name, path=candidate, is_builtin=False)
    return None


def resolve_hook(
    name: str, user_hooks_dir: Path | None = None, event: str | None = None
) -> HookInfo | None:
    return _find_builtin(name, event) or _find_user_hook(name, user_hooks_dir)


def resolve_script_names(
    names: list[str], user_hooks_dir: Path | None = None, event: str | None = None
) -> list[HookInfo]:
    """Resolve a list of hook names to HookInfo records, skipping unresolvable."""
    hooks: list[HookInfo] = []
    for script_name in names:
        hook = resolve_hook(script_name, user_hooks_dir, event)
        if hook:
            hooks.append(hook)
    return hooks


def resolve_hooks_for_event(
    cfg: Config, event: str, user_hooks_dir: Path | None = None
) -> list[HookInfo]:
    event_cfg = cfg.hooks.get(event)
    if not event_cfg:
        return []
    return resolve_script_names(event_cfg.scripts, user_hooks_dir, event)


PRE_RUNNER_AGENT = "claude-code"
"""The agent whose wire format the unmigrated `main()` path assumes.

TRANSITIONAL, and paired with `BuiltinHookSpec.migrated`. A builtin that has not
moved to the runner reads stdin itself, in Claude Code's shape, and exits with
its own code — so deploying one to any other agent is a guess. Named here rather
than spelled in the deploy path so that step 5 deletes the field, this constant
and the branches reading either, together.
"""


def builtin_migrated(name: str) -> bool:
    """Whether a builtin goes through the runner, False for anything unregistered.

    The read side of `BuiltinHookSpec.migrated`, for the same reason
    `builtin_signals` exists: callers stop reaching into `_BUILTIN_HOOKS`. A
    user hook answers False because the pre-runner path is exactly what it gets
    — the registry never heard of it and it has no `main(event)` to call.
    """
    spec = _BUILTIN_HOOKS.get(name)
    return spec.migrated if spec is not None else False


def builtin_signals(name: str, event: str | None = None) -> frozenset[Signal]:
    """Transcript signals a builtin declares at one placement.

    The read side of `BuiltinHookSpec.signals`, so callers stop reaching into
    `_BUILTIN_HOOKS`. A user hook resolves to the empty set rather than an
    error: nothing outside the registry declares signals, and a caller asking
    "what does this hook need" wants that answer, not an exception.

    `event` is optional because not every caller has one, and omitting it is
    answered conservatively rather than by unioning a per-placement spec: a
    caller that cannot say which placement it means is not owed a set that
    would omit a hook from a deploy.
    """
    spec = _BUILTIN_HOOKS.get(name)
    return spec.signals_for(event) if spec is not None else frozenset()
