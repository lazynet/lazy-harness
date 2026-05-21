"""Framework-provided default hook set.

The implicit hook configuration every profile starts with. User overrides
in `config.toml` replace per-event values; events not declared in user
config fall through to the defaults below.

See ADR-031 and specs/designs/2026-05-21-deploy-hook-defaults-design.md.
"""

from __future__ import annotations

from lazy_harness.core.config import HookEventConfig

DEFAULT_HOOKS: dict[str, list[str]] = {
    "session_start": ["context-inject"],
    "session_stop": ["session-export", "compound-loop", "engram-persist"],
    "session_end": ["session-end"],
    "pre_compact": ["pre-compact"],
    "post_compact": ["post-compact"],
    "pre_tool_use": ["pre-tool-use-security", "pre-tool-use-memory-size"],
    "post_tool_use": ["post-tool-use-format", "post-tool-use-sync-claude"],
}


def merge_with_defaults(user_hooks: dict[str, HookEventConfig]) -> dict[str, list[str]]:
    """Produce the effective hook event → script-names mapping.

    Rules:
    - For each event in DEFAULT_HOOKS: if user_hooks declares it (even with
      an empty list), use user_hooks[event].scripts. Otherwise use the
      default.
    - For each event in user_hooks but NOT in DEFAULT_HOOKS, include verbatim.
    - Events with an empty script list are kept in the result so callers
      can distinguish "explicit opt-out" from "not configured"; the engine
      drops empty events before writing settings.
    """
    effective: dict[str, list[str]] = {}
    for event, default_scripts in DEFAULT_HOOKS.items():
        if event in user_hooks:
            effective[event] = list(user_hooks[event].scripts)
        else:
            effective[event] = list(default_scripts)
    for event, hooks_cfg in user_hooks.items():
        if event not in DEFAULT_HOOKS:
            effective[event] = list(hooks_cfg.scripts)
    return effective
