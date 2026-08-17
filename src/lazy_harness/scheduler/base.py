"""Scheduler base types and protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


@dataclass
class SchedulerJob:
    name: str
    schedule: str
    command: str


class JobState(StrEnum):
    """Whether a job is registered with the OS scheduler.

    `UNKNOWN` exists so a backend that cannot introspect has a way to say so.
    Spelling that as `NOT_LOADED` is what made `lh status cron` report every
    job as failed on any platform without `launchctl`.

    This answers exactly one question — is the job registered — and
    deliberately not "is it healthy" or "did it run recently". Those come from
    the logs and the metrics DB, and conflating them is how a status view
    starts lying again.
    """

    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobRecord:
    """One job as the backend sees it on this machine.

    Discovery belongs to the backend because every part of it is
    backend-specific: where the unit files live, how they are named, how the
    schedule is spelled inside them, and how liveness is queried. The status
    views used to glob `~/Library/LaunchAgents` themselves, which made them
    macOS-only regardless of which backend was active.
    """

    name: str
    label: str
    schedule: str
    state: JobState
    detail: str = ""


@runtime_checkable
class SchedulerBackend(Protocol):
    def label_for(self, job: SchedulerJob) -> str: ...
    def install(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def status(self) -> list[dict[str, str]]: ...
    def discover(self) -> list[JobRecord]: ...
