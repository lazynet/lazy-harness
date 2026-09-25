"""Read-only evidence about one configured profile and its native hook file."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lazy_harness.agents.base import ConfigPlanner
from lazy_harness.agents.registry import agent_for_profile, binary_for_profile
from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir, expand_path
from lazy_harness.core.profile_identity import profile_identity, profile_source_dir
from lazy_harness.core.sync_agent_md import available_system_doc_sources
from lazy_harness.deploy.defaults import (
    DEFAULT_HOOKS,
    agent_scoped_omissions,
    suppressed_defaults,
)
from lazy_harness.deploy.engine import (
    ConfigPlannerRequiredError,
    UnknownProfileError,
    hook_entries_for,
)
from lazy_harness.deploy.skills import _skills_for_profile
from lazy_harness.hooks.event_surface import (
    operation_gaps_for_profile,
    uncarried_events_for_profile,
)
from lazy_harness.hooks.signal_gaps import gaps_for_profile


@dataclass(frozen=True)
class _RuntimeHook:
    event: str
    command: str | None
    matcher: str | None
    kind: str
    group_index: int


def _decode_hooks(raw: str) -> tuple[str, list[_RuntimeHook], dict]:
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("document is not an object")
        events = document.get("hooks", {})
        if not isinstance(events, dict):
            raise ValueError("hooks is not an object")
        found: list[_RuntimeHook] = []
        for event, groups in events.items():
            if not isinstance(event, str) or not isinstance(groups, list):
                raise ValueError("invalid hook event")
            for index, group in enumerate(groups):
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise ValueError("invalid hook group")
                matcher = group.get("matcher")
                if matcher is not None and not isinstance(matcher, str):
                    raise ValueError("invalid matcher")
                for hook in group["hooks"]:
                    if not isinstance(hook, dict):
                        raise ValueError("invalid hook handler")
                    command = hook.get("command")
                    kind = hook.get("type")
                    if command is not None and not isinstance(command, str):
                        raise ValueError("invalid hook command")
                    if kind is not None and not isinstance(kind, str):
                        raise ValueError("invalid hook type")
                    found.append(
                        _RuntimeHook(event, command, matcher or None, kind or "unknown", index)
                    )
        return "parsed", found, document
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return "unreadable", [], {}


def _native_hooks(path: Path) -> tuple[str, list[_RuntimeHook], dict]:
    try:
        return _decode_hooks(path.read_text())
    except FileNotFoundError:
        return "unknown", [], {}
    except (OSError, UnicodeError):
        return "unreadable", [], {}


def _managed_positions(
    agent_name: str, document: dict, runtime: Path, binary: str
) -> set[tuple[str, int]]:
    hooks = document.get("hooks", {})
    if agent_name == "codex":
        from lazy_harness.agents.codex import _owned_positions

        owned, _ = _owned_positions(document, hooks, binary=binary)
        return owned
    if agent_name == "claude-code":
        from lazy_harness.agents.claude_code import (
            _owned_binaries,
            _owned_hook_positions,
            _recorded_hook_positions,
        )

        try:
            ledger = (runtime / "lh-hook-ownership.json").read_text()
        except FileNotFoundError:
            ledger = None
        except (OSError, UnicodeError):
            return set()
        return _owned_hook_positions(
            _recorded_hook_positions(ledger),
            hooks,
            binaries=_owned_binaries(document, binary),
        )
    return set()


def inspect_profile(cfg: Config, name: str) -> dict[str, object]:
    """Resolve declarations and compare exact native event, command and matcher."""
    entry = cfg.profiles.items.get(name)
    if entry is None:
        raise UnknownProfileError(name, cfg.profiles.items)
    agent = agent_for_profile(cfg, name)
    source = profile_source_dir(cfg, name)
    runtime = expand_path(entry.config_dir)
    native_path = runtime / ("settings.json" if agent.name == "claude-code" else "hooks.json")
    native_state, actual, document = _native_hooks(native_path)
    remaining = list(actual)
    if not isinstance(agent, ConfigPlanner):
        raise ConfigPlannerRequiredError(name, agent.name)
    binary = binary_for_profile(cfg, name)
    resolved = hook_entries_for(cfg, name, binary, report=False)
    planned = agent.plan_config(resolved, {}, {}, binary=binary)
    planned_hooks = next(
        (
            op.artifact.content
            for op in planned
            if op.relative_path == native_path.relative_to(runtime) and op.artifact is not None
        ),
        "{}",
    )
    _, expected_entries, _ = _decode_hooks(planned_hooks)
    supports = agent.hook_events()
    hooks: dict[str, list[dict[str, object]]] = {}
    for event, entries in resolved.items():
        support = supports.get(event)
        native_event = support.native_name if support is not None else None
        rows: list[dict[str, object]] = []
        for entry_hook in entries:
            expected = next(
                (
                    item
                    for item in expected_entries
                    if item.event == native_event and item.command == entry_hook.command
                ),
                None,
            )
            if expected is None:
                continue
            expected_entries.remove(expected)
            matcher = expected.matcher
            if native_state != "parsed":
                deployed = native_state
            elif matched := next(
                (
                    item
                    for item in remaining
                    if (
                        item.event,
                        item.command,
                        item.matcher,
                        item.kind,
                    )
                    == (
                        expected.event,
                        expected.command,
                        expected.matcher,
                        expected.kind,
                    )
                ),
                None,
            ):
                remaining.remove(matched)
                deployed = "deployed"
            elif any(
                item.event == native_event and item.command == entry_hook.command
                for item in remaining
            ):
                deployed = "drift"
            else:
                deployed = "missing"
            rows.append(
                {
                    "command": entry_hook.command,
                    "matcher": matcher,
                    "ownership": entry_hook.ownership.value,
                    "configured": True,
                    "deployed": deployed,
                    "observed": "unknown",
                }
            )
        hooks[event] = rows

    managed = (
        _managed_positions(agent.name, document, runtime, binary)
        if native_state == "parsed"
        else set()
    )
    states = {row["deployed"] for rows in hooks.values() for row in rows}
    if any((item.event, item.group_index) in managed for item in remaining):
        states.add("drift")
    deployed_state = (
        native_state
        if native_state != "parsed"
        else "deployed"
        if states <= {"deployed"}
        else "drift"
    )
    docs = [str(path) for path in agent.system_docs()]
    doc_sources = available_system_doc_sources(source, config_dir() / "profiles", agent)
    skill_root = agent.skill_root(entry.config_dir)
    skills, _ = _skills_for_profile(source, agent.name)
    return {
        "profile": name,
        "agent": agent.name,
        "identity": profile_identity(name, entry),
        "source_dir": str(source),
        "runtime_dir": str(runtime),
        "configured": True,
        "deployed": deployed_state,
        "observed": "unknown",
        "hook_defaults": DEFAULT_HOOKS,
        "explicit_overrides": {
            event: list(value.scripts)
            for event, value in cfg.hooks.items()
            if value.scripts_configured or value.scripts
        },
        "suppressed_defaults": suppressed_defaults(cfg.hooks),
        "hooks": hooks,
        "runtime_only_hooks": [
            {
                "event": item.event,
                "command": item.command,
                "matcher": item.matcher,
                "type": item.kind,
                "ownership": "managed" if (item.event, item.group_index) in managed else "unknown",
            }
            for item in remaining
        ],
        "omissions": {
            "agent": [
                {"event": event, "hook": hook}
                for event, hook in agent_scoped_omissions(cfg.hooks, agent)
            ],
            "external_agent": [
                {"event": event, "command": hook.command}
                for event, value in cfg.hooks.items()
                for hook in value.external
                if hook.agents and agent.name not in hook.agents
            ],
            "signal": [asdict(gap) for gap in gaps_for_profile(cfg, name)],
            "operation": [asdict(gap) for gap in operation_gaps_for_profile(cfg, name)],
            "event": [asdict(gap) for gap in uncarried_events_for_profile(cfg, name)],
        },
        "system_docs": {
            "destinations": docs,
            "sources": [str(path) for path in doc_sources],
            "available": bool(doc_sources),
        },
        "skills": {
            "root": str(skill_root) if skill_root is not None else None,
            "sources": {name: str(path) for name, path in skills.items()},
            "available": skill_root is not None and bool(skills),
        },
    }
