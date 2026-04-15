"""Exceptions raised by the plugin system."""

from __future__ import annotations


class PluginError(Exception):
    """Base class for all plugin-system failures."""


class PluginNotFound(PluginError):
    """Raised when a plugin name is requested but not registered."""

    def __init__(self, *, kind: str, name: str) -> None:
        super().__init__(f"no {kind} plugin registered as {name!r}")
        self.kind = kind
        self.name = name


class PluginConflict(PluginError):
    """Raised when two plugins try to register the same (kind, name) pair."""

    def __init__(self, *, kind: str, name: str, origins: list[str]) -> None:
        joined = ", ".join(origins)
        super().__init__(f"conflicting {kind} registrations for {name!r}: {joined}")
        self.kind = kind
        self.name = name
        self.origins = origins


class PluginContractError(PluginError):
    """Raised when a plugin violates its Protocol contract at runtime."""
