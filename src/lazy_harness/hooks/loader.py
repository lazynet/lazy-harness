"""Hook discovery — resolve built-in and user hooks by name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir


@dataclass
class HookInfo:
    name: str
    path: Path
    is_builtin: bool


_BUILTIN_HOOKS: dict[str, str] = {
    "compound-loop": "lazy_harness.hooks.builtins.compound_loop",
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "post-tool-use-format": "lazy_harness.hooks.builtins.post_tool_use_format",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
    "pre-tool-use-security": "lazy_harness.hooks.builtins.pre_tool_use_security",
    "session-end": "lazy_harness.hooks.builtins.session_end",
    "session-export": "lazy_harness.hooks.builtins.session_export",
}


def list_builtin_hooks() -> list[str]:
    return list(_BUILTIN_HOOKS.keys())


def _find_builtin(name: str) -> HookInfo | None:
    module_path = _BUILTIN_HOOKS.get(name)
    if module_path is None:
        return None
    parts = module_path.split(".")
    base = Path(__file__).parent / "builtins" / f"{parts[-1]}.py"
    return HookInfo(name=name, path=base, is_builtin=True)


def _find_user_hook(name: str, user_hooks_dir: Path | None = None) -> HookInfo | None:
    hooks_dir = user_hooks_dir or config_dir() / "hooks"
    if not hooks_dir.is_dir():
        return None
    for candidate in [hooks_dir / f"{name}.py", hooks_dir / name]:
        if candidate.is_file():
            return HookInfo(name=name, path=candidate, is_builtin=False)
    return None


def resolve_hook(name: str, user_hooks_dir: Path | None = None) -> HookInfo | None:
    return _find_builtin(name) or _find_user_hook(name, user_hooks_dir)


def resolve_hooks_for_event(
    cfg: Config, event: str, user_hooks_dir: Path | None = None
) -> list[HookInfo]:
    event_cfg = cfg.hooks.get(event)
    if not event_cfg:
        return []
    hooks: list[HookInfo] = []
    for script_name in event_cfg.scripts:
        hook = resolve_hook(script_name, user_hooks_dir)
        if hook:
            hooks.append(hook)
    return hooks
