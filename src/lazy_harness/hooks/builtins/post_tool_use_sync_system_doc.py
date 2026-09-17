"""PostToolUse hook — regenerate a profile tree's system doc after segment edits.

Triggers when an edit tool touches **or removes** a segment file — `head.md`,
`common.md`, `tail.md`, an `_common/<agent>.md`, or one of their legacy
stem-keyed spellings — inside a `.../profiles/<dir>/` tree, and re-runs the
segmented system-doc generator against that tree. The trigger set is derived
from the generator's own segment roles (`segment_filenames()`), so a rename of
the segments cannot leave this hook watching names nobody edits any more.

A removal counts because the document is assembled from the segments: deleting
`_common/<agent>.md` re-renders it without that section, and deleting a `head`
or `tail` makes `sync_profiles` report the profile skipped rather than erase a
document it can no longer regenerate. This is the one builtin that reads
`ToolCall.deletes`; ADR-046 records why the other four must not.

The destinations it writes are the invoked profile's agent's, not this hook's:
the generator reads `system_docs()` off the adapter it is handed, so a profile
running Codex gets `AGENTS.md` regenerated from the same segments. Nothing in
the trigger is Claude Code-specific any more, and decision 5 renames the hook
itself to match: `post_tool_use_sync_claude` is now
`post_tool_use_sync_system_doc`, and the registry key
`post-tool-use-sync-claude` stays as an alias so a `config.toml` naming it
keeps deploying this module until the operator renames it.

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
from lazy_harness.core.sync_agent_md import segment_filenames, sync_profiles
from lazy_harness.hooks.builtins._shared import EDIT_TOOLS

# The tool names this hook inspects — `_shared.EDIT_TOOLS`, not a copy of it.
# `tests/unit/test_hook_matcher_coverage.py` asserts the matcher the registry
# deploys covers every one of them, so the gate below and the subscription
# declared outside cannot drift apart.
INSPECTED_TOOLS = EDIT_TOOLS

# Derived from the segment roles the generator declares, not listed here
# (decision 5, ADR-043). A static list is how renaming the segments stops firing
# the hook that regenerates the document from them: the rename lands, the hook
# keeps watching three filenames nobody edits any more, and the deployed
# contract file quietly goes stale with nothing on any channel to say so.
SEGMENT_FILES = segment_filenames()


def _profiles_dir_for(path: Path) -> Path | None:
    """If `path` lives at `<profiles>/<name>/<segment>` or
    `<profiles>/_common/<segment>`, return `<profiles>`. Else None."""
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

    The caller passes the *deleted* paths alongside the edited ones. A removed
    segment changes the assembled document exactly as an edited one does, and
    this hook is the only reader of `ToolCall` for which that is true — which
    is why ADR-046 put deletes in their own field and made each reader ask.
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
    # Deletes included, and `paths` deliberately not used: that property also
    # carries `reads`, and a *read* of a segment must not regenerate anything.
    trees = _trees_touched(tuple(edit.path for edit in tool.edits) + tool.deletes)
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
        # `[agent].type` names globally. `system_docs()` is read off that
        # adapter, so resolving it globally wrote one agent's contract file
        # into a profile running another.
        # The firing profile's adapter is the fallback for a directory the
        # config does not name. `cfg` is what makes the rest per profile:
        # handing one adapter to a walk over the whole tree only moved the
        # defect, from the global agent to whichever profile fired the hook.
        agent = agent_dir_for(cfg, event.profile)[0]
        for tree in trees:
            sync_profiles(tree, agent, cfg=cfg)
    except Exception:
        pass
    return HookDecision()
