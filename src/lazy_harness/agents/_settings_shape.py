"""Port of Claude Code 2.1.278's settings.json hook-shape detector.

Decompiled from `/Users/lazynet/.local/share/claude/versions/2.1.278` (the
shipped binary's `gf`/`uW`/`rue`/`r7`/`zs` functions). Claude Code scans every
top-level settings.json key three levels deep for anything that looks like a
hook declaration or an inline permission decision, and discards the *entire
file* — no hooks, no permissions, no env, no statusLine — the instant one
matches. `lh_hook_ownership.managed[i].group` matched, because a recorded
ledger entry is `{"matcher": ..., "hooks": [...]}` by construction.

`_plan_settings` runs this over the document it is about to write, so a
settings.json the agent would discard is refused instead of deployed. The
regression test over the goldens is the same call at build time.
"""

from __future__ import annotations

# Native event names. A key with one of these names is exempt from the
# hook-group check at its own level (`r7`'s `"matcher" not in e and any(...)`
# guard) — Claude Code's own `hooks` block legitimately contains objects
# shaped like this, so scanning under the literal `hooks` key is skipped
# entirely by the top-level and recursive scanners alike.
_EVENT_NAMES: tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Notification",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "SessionStart",
    "SessionEnd",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "PreModelSwitch",
    "PostModelSwitch",
    "PermissionRequest",
    "PermissionDenied",
    "Setup",
    "TeammateIdle",
    "TaskCreated",
    "TaskCompleted",
    "Elicitation",
    "ElicitationResult",
    "ConfigChange",
    "WorktreeCreate",
    "WorktreeRemove",
    "InstructionsLoaded",
    "CwdChanged",
    "FileChanged",
    "DirectoryAdded",
    "MessageDisplay",
)

# Top-level keys Claude Code never scans at all — first-party documents it
# already understands the shape of.
_UNSCANNED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "mcpServers",
        "managedMcpServers",
        "lspServers",
        "pluginConfigs",
        "enabledPlugins",
        "extraKnownMarketplaces",
        "env",
        "skillOverrides",
        "modelSettings",
    }
)

# Event names whose payload is an inline permission/tool-use decision (`zs`),
# not a hook group — a non-empty value under either key is fatal at any depth.
_INLINE_DECISION_KEYS: frozenset[str] = frozenset({"PreToolUse", "PermissionRequest"})


def _looks_like_an_inline_decision(value: object) -> bool:
    """`zs`: an inline permission/tool-use decision object."""
    if not isinstance(value, dict):
        return False
    return any(
        key in _INLINE_DECISION_KEYS and payload is not None and payload != []
        for key, payload in value.items()
    )


def _looks_like_a_hook_group(value: object) -> bool:
    """`r7`: does this object look like a hook declaration?"""
    if not isinstance(value, dict):
        return False
    if "matcher" not in value and any(key in _EVENT_NAMES for key in value):
        return False
    hooks = value.get("hooks")
    if isinstance(hooks, list):
        return len(hooks) > 0
    return (
        bool(hooks)
        and isinstance(hooks, dict)
        and ("matcher" in value or isinstance(hooks.get("type"), str))
    )


def _scan(
    value: object,
    depth: int,
    *,
    check_hook_groups: bool,
    unscanned_keys: frozenset[str],
    inside_hooks_list: bool,
    path: str,
) -> str | None:
    """`rue`: the recursive depth-3 scan for either fatal shape."""
    if _looks_like_an_inline_decision(value):
        return path
    if check_hook_groups and _looks_like_a_hook_group(value):
        return path
    if depth == 0 or not isinstance(value, (dict, list)):
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            hit = _scan(
                item,
                depth - 1,
                check_hook_groups=check_hook_groups,
                unscanned_keys=unscanned_keys,
                inside_hooks_list=inside_hooks_list,
                path=f"{path}[{index}]",
            )
            if hit is not None:
                return hit
        return None
    if inside_hooks_list and isinstance(value.get("type"), str):
        return None
    for key, item in value.items():
        if key in unscanned_keys:
            continue
        hit = _scan(
            item,
            depth - 1,
            check_hook_groups=check_hook_groups and key not in _EVENT_NAMES,
            unscanned_keys=unscanned_keys,
            inside_hooks_list=(key == "hooks" and isinstance(item, list)),
            path=f"{path}.{key}",
        )
        if hit is not None:
            return hit
    return None


def fatal_hook_shape(document: object) -> str | None:
    """`uW`/`gf`: the JSON path of the first shape Claude Code 2.1.278 treats as
    a fatal settings error, or `None` when it would accept the document whole.

    A `lh_hook_ownership`-shaped top-level key trips this at
    `$.lh_hook_ownership.managed[0].group` — the recorded ledger entry is a
    `{"matcher": ..., "hooks": [...]}` object three levels down.
    """
    if not isinstance(document, dict):
        return None
    if _looks_like_an_inline_decision(document):
        return "$"
    for key, value in document.items():
        if key == "hooks" or key in _UNSCANNED_TOP_LEVEL_KEYS:
            continue
        hit = _scan(
            value,
            3,
            check_hook_groups=key not in _EVENT_NAMES,
            unscanned_keys=_UNSCANNED_TOP_LEVEL_KEYS,
            inside_hooks_list=False,
            path=f"$.{key}",
        )
        if hit is not None:
            return hit
    return None
