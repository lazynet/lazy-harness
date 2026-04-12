"""Scheduler base types and protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SchedulerJob:
    name: str
    schedule: str
    command: str


@runtime_checkable
class SchedulerBackend(Protocol):
    def install(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def status(self) -> list[dict[str, str]]: ...
