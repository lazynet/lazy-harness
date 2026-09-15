"""Agent adapter protocol — defines what an agent adapter must expose."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

# --- the canonical hook contract (ADR-041) ------------------------------
#
# Every adapter translates its agent's native payload into these types and back.
# They are the only vocabulary a builtin hook is allowed to reason about; an
# adapter that cannot fill a field leaves it `None`, and the hook that needs it
# is reported unavailable for that agent rather than run against a hole.


class Verdict(StrEnum):
    """A permission decision, in the four states the agents between them speak."""

    ALLOW = "allow"
    """Explicit approval, skipping the prompt. Must be reached deliberately."""
    DENY = "deny"
    ASK = "ask"
    BLOCK = "block"
    """Stop-class events: keep the agent working rather than ending the turn."""


class Operation(StrEnum):
    """What a tool call does, in the terms the builtins actually reason about.

    Derived from what the hooks consume, not from what a tool API offers:
    knowing that an operation modifies a file does not let a size guard compute
    how large it will be afterwards, which is why `ToolCall` carries the
    normalised arguments beside the operation.
    """

    RUN_COMMAND = "run_command"
    READ_FILE = "read_file"
    MODIFY_FILE = "modify_file"


class Signal(StrEnum):
    """A named thing a hook needs to read out of a transcript.

    Declared rather than reduced to `requires_transcript: bool`, so a reader
    that delivers messages and tokens but has no concept of an explicit goal
    cannot silently re-enable a guard that would then always pass.
    """

    MESSAGES = "messages"
    TOOL_CALLS = "tool_calls"
    TOKEN_USAGE = "token_usage"
    GOAL_STATUS = "goal_status"


@dataclass(frozen=True)
class FileEdit:
    """One file a tool call modifies, with whatever the tool disclosed about how.

    `content` and `replacements` are both present because the agents disclose
    different halves: a whole-file write gives text, a patch gives pairs.
    """

    path: Path
    is_create: bool = False
    content: str | None = None
    replacements: tuple[tuple[str, str], ...] = ()
    replace_all: bool = False


@dataclass(frozen=True)
class ToolCall:
    """One tool call, normalised away from the agent's own argument names.

    Both collections are plural because Codex's `apply_patch` and Copilot's
    `edit` can touch several files in one call; a singular `file_path` is a
    Claude Code assumption a path guard would silently under-enforce elsewhere.
    """

    native_name: str
    operation: Operation | None
    """`None` for an operation no builtin reasons about."""
    command: str | None = None
    reads: tuple[Path, ...] = ()
    offset: int | None = None
    """`None` means unbounded — not 0, which is a legitimate start offset."""
    limit: int | None = None
    edits: tuple[FileEdit, ...] = ()
    raw_input: object | None = None
    """Adapters only. A builtin reading this is a normalisation that failed."""

    @property
    def paths(self) -> tuple[Path, ...]:
        return self.reads + tuple(edit.path for edit in self.edits)


@dataclass(frozen=True)
class HookEvent:
    """One hook invocation, normalised across providers.

    Carries every field a payload can name so that no builtin has to reach into
    `raw`; the moment one does, the normalisation is a fiction.
    """

    event: str
    """Canonical event name, not the agent's wire name."""
    profile: str
    session_id: str
    cwd: Path
    transcript_path: Path | None
    tool: ToolCall | None = None
    """The canonical view of the tool call. There is deliberately no
    `tool_name`/`tool_input` beside it: two representations of one thing is how
    builtins keep reading native argument names."""
    tool_use_id: str | None = None
    tool_response: object | None = None
    """Unconstrained on purpose. Copilot delivers a `{result_type, ...}` mapping
    and the Claude SDK declares it untyped, so `dict` would be a lie that fails
    at the first `.get()`."""
    prompt: str | None = None
    permission_mode: str | None = None
    source: str | None = None
    """session_start: startup | resume | clear | compact."""
    trigger: str | None = None
    """pre_compact: manual | auto."""
    stop_hook_active: bool = False
    message: str | None = None
    """notification."""
    raw: dict | None = None
    """The untranslated payload. Adapters only."""


@dataclass(frozen=True)
class HookDecision:
    """What a hook decided, before any agent's serialisation touches it."""

    verdict: Verdict | None = None
    """`None` abstains: no permission decision at all.

    Not `ALLOW`. A hook that merely fails to object must not thereby approve —
    that would turn every command a security guard does not recognise into an
    explicit, prompt-skipping approval.
    """
    reason: str = ""
    additional_context: str = ""
    system_message: str = ""
    stop: bool = False
    suppress_output: bool = False


@dataclass(frozen=True)
class HookOutput:
    """The three channels an agent actually reads, already serialised.

    `stdout` is `str`, not a mapping: the design promises byte-identical output,
    and a mapping defers serialisation to whoever writes it. The adapter owns
    the bytes; the runner writes the string it is given and never re-encodes.

    `stderr` is a channel of its own because a blocking hook's reason reaches
    the user through it — both blocking builtins write there and exit 2, and a
    two-channel pair would drop the refusal silently.
    """

    stdout: str | None
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class HookSupport:
    """How one agent delivers one event, and which decisions it honours there.

    `verdicts` is declared rather than reduced to a `can_block` field because a
    verdict an agent does not honour does not fail loudly: Codex logs
    `unsupported permissionDecision:ask` and runs the tool anyway. With the set
    declared, deploy can refuse the configuration instead of discovering it
    while a tool call is pending.
    """

    native_name: str
    """The wire name, with the agent's own casing."""
    verdicts: frozenset[Verdict] = field(default_factory=frozenset)

    @property
    def can_block(self) -> bool:
        return bool(self.verdicts & {Verdict.DENY, Verdict.BLOCK})


@dataclass(frozen=True)
class ConfigArtifact:
    """A fully merged config document, ready for the engine to write."""

    relative_path: Path
    content: str


@dataclass(frozen=True)
class WriteOp:
    """One write or delete in a deploy plan, with its diagnostics.

    Deletion is explicit — `artifact is None` — because an adapter that stops
    generating a file must be able to say so. Without it, a file the harness
    wrote in an earlier release stays forever.
    """

    artifact: ConfigArtifact | None
    relative_path: Path
    preserved: list[str] = field(default_factory=list)
    """Foreign entries kept, for the deploy report."""
    dropped: list[str] = field(default_factory=list)
    """Harness entries no longer generated."""
    repaired: list[str] = field(default_factory=list)
    """Entries the agent would have rejected."""


HEADLESS_TIERS: tuple[str, ...] = ("fast", "balanced", "deep")
"""Provider-neutral capability tiers a caller may ask for.

The vocabulary lives here so the CLI and every adapter agree on it; the
mapping from a tier to a concrete model id is the adapter's business.
"""


@dataclass(frozen=True)
class HeadlessResult:
    """One headless invocation, normalised across providers.

    Token fields are `None` when the provider did not report them — never 0.
    A zero enters a cost report as a fact, and "this provider has no prompt
    cache" is not the same fact as "this call cached nothing".
    """

    success: bool
    output: str
    exit_code: int
    cost_usd: float | None = None
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    num_turns: int | None = None
    raw: dict | None = None
    # The provider's own id for the conversation. `lh exec` pins it up front
    # when the adapter can, and reconciles against this when it cannot.
    session_id: str | None = None


@runtime_checkable
class HeadlessAgent(Protocol):
    """Optional capability: an agent that can be driven non-interactively.

    Deliberately separate from `AgentAdapter`. An adapter that cannot be
    invoked headlessly simply does not implement these, and `lh exec` refuses
    it up front instead of exec'ing something whose output it cannot parse.
    """

    def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
        """Resolve a model id. `explicit` wins; `None`/`None` means provider default.

        Raises ValueError for a tier this provider does not map.
        """
        ...

    def headless_argv(self, *, model: str | None, allowed_tools: list[str] | None) -> list[str]:
        """Build the argv that follows argv[0], excluding the prompt.

        The prompt travels on stdin, so argv stays bounded regardless of
        prompt size. `allowed_tools` is tri-state: `None` leaves the
        provider's own policy alone, `[]` denies every tool it can be told
        to deny, and a list grants exactly those.
        """
        ...

    def parse_headless_result(self, stdout: str, exit_code: int) -> HeadlessResult:
        """Normalise the provider's stdout into a `HeadlessResult`.

        Must not raise: unparseable output degrades to `output=stdout`,
        `raw=None`, and metadata left `None`.
        """
        ...


@runtime_checkable
class SessionPinningAgent(Protocol):
    """Optional capability: an agent whose session id the caller can choose.

    Kept out of `HeadlessAgent` on purpose. Adding it there would make every
    adapter that cannot pin a session fail `isinstance` and be refused
    outright, when the right behaviour is to run it and resolve the session id
    after the fact.
    """

    def session_argv(self, session_id: str) -> list[str]:
        """Argv fragment that pins the conversation to `session_id`."""
        ...


@dataclass(frozen=True)
class TokenUsage:
    """Per-turn accounting, in the terms every provider can be made to answer.

    Every field is `int | None` for `HeadlessResult`'s reason: a provider that
    reported no cache field and a turn that cached nothing are different facts,
    and a 0 merges them into the second.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None


@dataclass(frozen=True)
class GoalStatus:
    """An explicit, user-set objective as the agent recorded it.

    `condition` and `met` are both optional because the *presence* of the
    record is the signal `stop_verify_guard` reads; an agent that marks a goal
    without restating its text still delivers `GOAL_STATUS`.
    """

    condition: str | None = None
    met: bool | None = None


@dataclass(frozen=True)
class TranscriptEvent:
    """One thing read out of a transcript, tagged with the signal it carries.

    Tagged with `Signal` rather than with a parallel `kind` enum on purpose:
    decision 11 makes transcript dependence a declaration in that exact
    vocabulary, and a second enum would let a reader declare `GOAL_STATUS` and
    yield events no consumer of that declaration recognises. With one
    vocabulary, `signals()` is checkable against what `read()` actually emits.

    One transcript line can yield several events — an assistant turn with two
    tool calls and a usage record is one line and four events — so the unit is
    the signal occurrence, not the line.

    Field-per-concept, like `HookEvent`, so that no consumer has to reach into
    `raw`. The fields a signal does not carry stay `None`.
    """

    signal: Signal
    timestamp: datetime | None = None
    role: str | None = None
    """messages: 'user' | 'assistant' | whatever the provider names its turns."""
    text: str | None = None
    """messages: the turn's text with non-text blocks dropped."""
    tool: ToolCall | None = None
    """tool_calls: the same normalised call `HookEvent.tool` carries."""
    tool_use_id: str | None = None
    """tool_calls: the provider's own id, which pairs a call with its result."""
    usage: TokenUsage | None = None
    """token_usage."""
    goal: GoalStatus | None = None
    """goal_status."""
    raw: dict | None = None
    """The untranslated entry. Adapters only."""


@runtime_checkable
class TranscriptReader(Protocol):
    """Optional capability: an agent whose transcript we can read.

    Modelled on `HeadlessAgent`, and separate from `AgentAdapter` for the same
    reason: an agent with no readable transcript does not implement this, and a
    caller refuses it up front rather than parsing a shape it is guessing.
    """

    def locate_sessions(self, config_dir: Path, since: datetime | None) -> Iterator[Path]:
        """Transcripts under `config_dir`, most useful first-come.

        `config_dir` is a parameter rather than adapter state because adapters
        are constructed with no arguments (`registry.py`: a bare `cls()`), so
        one instance serves every profile — and a profile is exactly what
        disambiguates two config dirs served by the same agent.

        `since` filters by last modification; `None` means no filter.
        """
        ...

    def read(self, path: Path) -> Iterator[TranscriptEvent]:
        """Every signal occurrence in one transcript, in file order.

        A transcript is read while the agent is still writing it, so an absent
        file, an unopenable one, a half-written last line, a line corrupted by
        an interrupted write and a byte that is not valid UTF-8 are all
        ordinary rather than exceptional: each is skipped, reading continues,
        and none of them raises.
        """
        ...

    def signals(self) -> set[Signal]:
        """Which signals this reader can actually deliver.

        Lives on the reader, not only on the hook, because decision 11 makes
        transcript dependence a *declared* capability — and a declaration that
        lives only in the hook cannot be checked against the reader that is
        supposed to satisfy it.
        """
        ...


@dataclass(frozen=True)
class HookEntry:
    """One hook command to be installed under an event.

    `matcher` overrides the agent's default matcher for this event when set.
    Used so a single event (e.g. `pre_tool_use`) can dispatch hooks to
    different tool matchers (`Bash` vs `Edit|Write`).
    """

    command: str
    matcher: str | None = None


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that all agent adapters must implement."""

    @property
    def name(self) -> str:
        """Unique identifier for this agent type."""
        ...

    def config_dir(self, profile_config_dir: str) -> Path:
        """Resolve the agent's config directory for a profile."""
        ...

    def supported_hooks(self) -> list[str]:
        """Canonical hook event names this agent supports.

        Derived from `hook_events()`, never declared separately: the mapping
        from canonical to native names must exist in exactly one place.
        """
        ...

    def hook_events(self) -> dict[str, HookSupport]:
        """Canonical event name -> how this agent delivers it.

        An absent key means the agent does not deliver that event at all,
        which is a different statement from delivering it and ignoring the
        verdict — `HookSupport.verdicts` carries the second.
        """
        ...

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        """Translate this agent's native hook payload into the canonical event."""
        ...

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        """Serialise a decision into the three channels this agent reads.

        Raises ValueError for a verdict this agent does not honour on this
        event. Deploy refuses that configuration up front, so the runner never
        reaches it — but it must raise rather than silently emit nothing, which
        on a blocking hook would read as approval.
        """
        ...

    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate agent-native hook config (e.g., settings.json for Claude Code)."""
        ...

    def generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        """Generate agent-native MCP server config block.

        `servers` is a mapping of server name -> declarative entry
        (`{"command": str, "args": list[str], "env": dict[str, str] | None}`).
        Returns a dict ready to merge into the agent's settings file.
        """
        ...

    def resolve_binary(self) -> Path | None:
        """Locate the agent's executable on disk.

        Returns the absolute path, or None if not found. Implementations
        should prefer well-known install locations (e.g. version-managed
        directories) over a generic PATH lookup, and must avoid resolving
        to wrappers that would shell back into `lh run` (recursion).
        """
        ...

    def env_var(self) -> str:
        """Name of the environment variable that selects the profile config dir."""
        ...

    def global_config_link(self) -> Path | None:
        """Canonical global symlink for this agent (e.g. ~/.claude).

        Return None if the agent does not use a global symlink convention.
        `lh deploy` only creates the symlink when this is non-None.
        """
        ...

    def mcp_config_file(self) -> str:
        """Filename inside the config dir that holds MCP server config.

        Claude Code: '.claude.json'. Return empty string if MCP config
        is merged into the main settings file.
        """
        ...

    def session_dirs(self) -> dict[str, str]:
        """Subdirectory names for agent-managed session artefacts.

        Keys: 'sessions', 'logs', 'queue'. Empty string means not available.
        Claude Code: {'sessions': 'projects', 'logs': 'logs', 'queue': 'queue'}
        """
        ...

    def system_doc_name(self) -> str:
        """Primary system-instruction document filename (e.g. 'CLAUDE.md').

        Return empty string for agents that use a different injection mechanism.
        """
        ...

    def process_name(self) -> str:
        """Process name to use as argv[0] when exec'ing the resolved binary.

        Lets process-detection tools recognize the agent by name even when
        `resolve_binary()` resolves to a versioned install path. Return empty
        string to fall back to the resolved binary path as argv[0].
        """
        ...


@runtime_checkable
class ConfigPlanner(Protocol):
    """Optional capability: an adapter that plans its own config documents.

    Separate from `AgentAdapter` for the same reason `HeadlessAgent` is: an
    adapter that has not been taught to merge its native config yet should be
    refused up front, not discovered mid-deploy. Merging is an adapter
    operation because parsing never was agent-neutral; writing is the engine's.
    """

    def config_targets(self) -> list[Path]:
        """Every file this adapter may read or write, relative to the config dir."""
        ...

    def plan_config(
        self,
        hooks: dict[str, list[HookEntry]],
        servers: dict[str, dict],
        existing: dict[Path, str],
        *,
        binary: str | None = None,
    ) -> list[WriteOp]:
        """One call produces the complete set of operations.

        `existing` holds every target that exists, by path, so an adapter whose
        hooks and MCP servers share one file emits a single write for it and
        cannot overwrite its own earlier result.

        `binary` is the launcher this deploy writes into the generated commands,
        resolved per profile by `binary_for_profile`. It is declared here because
        the engine has to pass it and an adapter that stamps the writing launcher
        cannot derive it: a profile whose only hooks are third-party generates no
        launcher invocation to read it off. Adapters that do not stamp one ignore
        it.
        """
        ...
