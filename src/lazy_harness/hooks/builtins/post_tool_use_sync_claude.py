"""PostToolUse hook — regenerate a profile tree's system doc after segment edits.

Triggers when an Edit/Write touches a `CLAUDE.head.md`, `CLAUDE.tail.md`, or
`CLAUDE.common.md` inside a `.../profiles/<dir>/` tree, and re-runs the
segmented system-doc generator against that tree.

The name it writes is the invoked profile's agent's, not this hook's: the
generator reads `system_doc_name()` off the adapter it is handed, so a profile
running Codex gets `AGENTS.md` regenerated from its `AGENTS.*` segments. Only
the *trigger* is Claude Code-specific, which is why the hook's name is.

Fail-soft: any error is swallowed and the hook abstains, because a sync
failure must never block the agent's progress.
"""

from __future__ import annotations

from pathlib import Path

# `HookEvent` is imported at runtime, not under `TYPE_CHECKING`:
# `test_every_builtin_main_takes_an_event_and_returns_a_decision` resolves this
# module's annotations with `typing.get_type_hints`, which evaluates the
# forward reference `from __future__ import annotations` leaves behind.
from lazy_harness.agents.base import HookDecision, HookEvent
from lazy_harness.core.sync_agent_md import sync_profiles

# Segment filenames are Claude Code-specific. A future adapter extension may
# make these dynamic; for now the hook name intentionally stays claude-specific.
# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
INSPECTED_TOOLS = frozenset({"Edit", "Write"})

SEGMENT_FILES = {"CLAUDE.head.md", "CLAUDE.tail.md", "CLAUDE.common.md"}


def _profiles_dir_for(path: Path) -> Path | None:
    """If `path` lives at `<profiles>/<name>/<segment>` or
    `<profiles>/_common/CLAUDE.common.md`, return `<profiles>`. Else None."""
    parts = path.parts
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == "profiles":
            return Path(*parts[: i + 1])
    return None


def _trees_touched(paths: tuple[Path, ...]) -> list[Path]:
    """Distinct profile trees the edited segments live in, in payload order.

    `ToolCall.edits` is plural because Codex's `apply_patch` and Copilot's
    `edit` can touch several files in one call. Claude Code never delivers more
    than one, so today this returns zero or one tree and the loop is inert —
    but reading only `edits[0]` would bake the singular assumption into the
    hook rather than into the adapter, which is the shape this migration exists
    to remove.
    """
    trees: list[Path] = []
    for path in paths:
        if path.name not in SEGMENT_FILES:
            continue
        tree = _profiles_dir_for(path)
        if tree is not None and tree not in trees:
            trees.append(tree)
    return trees


def main(event: HookEvent) -> HookDecision:
    """Regenerate the system doc of every profile tree a segment edit touched."""
    tool = event.tool
    # Narrowed on the native tool name rather than on `Operation.MODIFY_FILE`,
    # which also covers `NotebookEdit` (`agents/claude_code.py:97`). The second
    # gate below is a *filename* match, not an extension, so a notebook whose
    # normalised path is named `CLAUDE.head.md` would clear it: switching to the
    # operation would widen this hook onto notebooks for the first time, and no
    # channel it writes on would show it. `INSPECTED_TOOLS` stays the gate.
    if tool is None or tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()
    trees = _trees_touched(tuple(edit.path for edit in tool.edits))
    if not trees:
        return HookDecision()
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import agent_dir_for

        # A missing or unreadable config must not silently cancel the sync:
        # fall back to the default adapter, which is what `agent_dir_for`
        # degrades a `None` config to.
        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        # The directory half is unused: this hook writes nothing under the
        # agent's runtime dir. What it needs from `agent_dir_for` is the other
        # half — which agent *this profile* runs, rather than whichever one
        # `[agent].type` names globally. `system_doc_name()` is read off that
        # adapter, so resolving it globally wrote one agent's contract file
        # into a profile running another.
        agent = agent_dir_for(cfg, event.profile)[0]
        for tree in trees:
            sync_profiles(tree, agent)
    except Exception:
        pass
    return HookDecision()
