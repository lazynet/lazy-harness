"""Tests for the cron scheduler backend stub."""

from __future__ import annotations

import pytest

from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.cron import CronBackend


def test_cron_install_raises_instead_of_faking_success() -> None:
    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    with pytest.raises(NotImplementedError):
        CronBackend().install([job])


def test_cron_uninstall_is_noop_without_raising() -> None:
    assert CronBackend().uninstall([]) == []


def test_cron_status_is_empty_without_raising() -> None:
    assert CronBackend().status() == []
