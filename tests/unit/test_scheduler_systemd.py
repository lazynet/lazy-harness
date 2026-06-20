"""Tests for the systemd scheduler backend stub."""

from __future__ import annotations

import pytest

from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.systemd import SystemdBackend


def test_systemd_install_raises_instead_of_faking_success() -> None:
    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    with pytest.raises(NotImplementedError):
        SystemdBackend().install([job])


def test_systemd_uninstall_is_noop_without_raising() -> None:
    assert SystemdBackend().uninstall([]) == []


def test_systemd_status_is_empty_without_raising() -> None:
    assert SystemdBackend().status() == []
