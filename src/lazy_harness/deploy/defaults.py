"""Framework-provided default hook set.

The implicit hook configuration every profile starts with. User overrides
in `config.toml` replace per-event values; events not declared in user
config fall through to the defaults below.

See ADR-031 and specs/designs/2026-05-21-deploy-hook-defaults-design.md.
"""

from __future__ import annotations

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.core.config import HookEventConfig
from lazy_harness.plugins.builtins import _SYSTEM_DOC_HOOKS


def _derive_default_hooks() -> dict[str, list[str]]:
    """The default hook set, computed from the capability registry.

    This was a dict literal maintained beside the registration table, so a hook
    could be registered and forgotten here — implemented, wired, and never
    deployed, with no error from the framework and none from the agent. There
    is now one place to add a hook.

    Order is preserved: `capabilities()` returns registration order, and the
    generated `settings.json` lists hooks in the order this mapping gives.
    """
    from lazy_harness.plugins.builtins import builtin_registry

    derived: dict[str, list[str]] = {}
    for cap in builtin_registry().capabilities(kind="hook"):
        if not cap.enabled_by_default:
            continue
        # `hooks.<event>.scripts`
        event = cap.config_path.split(".")[1]
        derived.setdefault(event, []).append(cap.name)
    return derived


DEFAULT_HOOKS: dict[str, list[str]] = _derive_default_hooks()




def merge_with_defaults(
    user_hooks: dict[str, HookEventConfig],
    agent: AgentAdapter,
) -> dict[str, list[str]]:
    """Produce the effective hook event → script-names mapping.

    Rules:
    - For each event in DEFAULT_HOOKS: if user_hooks declares it (even with
      an empty list), use user_hooks[event].scripts. Otherwise use the
      default, filtered by agent capabilities.
    - For each event in user_hooks but NOT in DEFAULT_HOOKS, include verbatim.
    - Events with an empty script list are kept so callers can distinguish
      "explicit opt-out" from "not configured"; the engine drops empty events
      before writing settings.
    - Hooks in _SYSTEM_DOC_HOOKS are omitted when agent.system_doc_name() is
      empty (the agent does not use a file-based system instruction doc).
    """
    has_system_doc = bool(agent.system_doc_name())

    effective: dict[str, list[str]] = {}
    for event, default_scripts in DEFAULT_HOOKS.items():
        if event in user_hooks:
            effective[event] = list(user_hooks[event].scripts)
        else:
            filtered = [s for s in default_scripts if s not in _SYSTEM_DOC_HOOKS or has_system_doc]
            effective[event] = filtered
    for event, hooks_cfg in user_hooks.items():
        if event not in DEFAULT_HOOKS:
            effective[event] = list(hooks_cfg.scripts)
    return effective
