"""Hybrid plugin registry: built-in registrations + Python entry-point discovery.

Name resolution order: built-in first, then entry points (prefixed `ext:`).
Nothing is instantiated unless a caller explicitly resolves it — discovery
is not activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lazy_harness.plugins.errors import PluginConflict, PluginNotFound


@dataclass(frozen=True)
class PluginInfo:
    name: str
    origin: str  # "builtin" | "ext:<dist-name>"
    impl: type[Any]


class PluginRegistry:
    def __init__(self) -> None:
        self._builtins: dict[type, dict[str, type[Any]]] = {}
        self._external: dict[type, dict[str, PluginInfo]] = {}

    def register_builtin(self, kind: type, impl: type[Any]) -> None:
        name = getattr(impl, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{impl!r} has no valid .name class attribute")
        bucket = self._builtins.setdefault(kind, {})
        if name in bucket:
            raise PluginConflict(
                kind=kind.__name__,
                name=name,
                origins=["builtin", "builtin"],
            )
        bucket[name] = impl

    def resolve(self, kind: type, name: str) -> type[Any]:
        bucket = self._builtins.get(kind, {})
        if name in bucket:
            return bucket[name]
        ext = self._external.get(kind, {})
        if name in ext:
            return ext[name].impl
        raise PluginNotFound(kind=kind.__name__, name=name)

    def list_available(self, kind: type) -> list[PluginInfo]:
        result: list[PluginInfo] = []
        for name, impl in self._builtins.get(kind, {}).items():
            result.append(PluginInfo(name=name, origin="builtin", impl=impl))
        for info in self._external.get(kind, {}).values():
            result.append(info)
        return result
