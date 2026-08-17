"""Tests for the crontab scheduler backend."""

from __future__ import annotations

import subprocess

from lazy_harness.scheduler.base import JobState, SchedulerJob


class FakeCrontab:
    """Stands in for the user's crontab across a sequence of calls."""

    def __init__(self, initial: str = "", *, missing: bool = False) -> None:
        self.content = initial
        self.missing = missing
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], *, input: str | None = None):  # noqa: A002
        self.calls.append(argv)
        if self.missing:
            raise FileNotFoundError("crontab")
        if argv[1:] == ["-l"]:
            if not self.content:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="no crontab for lazynet"
                )
            return subprocess.CompletedProcess(argv, 0, stdout=self.content, stderr="")
        self.content = input or ""
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_install_preserves_foreign_entries() -> None:
    """The delimited block is what makes uninstall safe on a shared crontab."""
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab("0 4 * * * /home/me/backup.sh\n")
    CronBackend(runner=fake).install(
        [SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")]
    )

    assert "/home/me/backup.sh" in fake.content
    assert fake.content.index("backup.sh") < fake.content.index("# BEGIN lazy-harness")
    assert "# lazy-harness:qmd-sync" in fake.content
    assert "# END lazy-harness" in fake.content
    # cron's default PATH is /usr/bin:/bin, which is the most common reason a
    # cron job fails.
    assert "PATH=" in fake.content


def test_install_replaces_a_previous_block_instead_of_appending() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab("0 4 * * * /home/me/backup.sh\n")
    backend = CronBackend(runner=fake)
    job = SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")
    backend.install([job])
    backend.install([job])

    assert fake.content.count("# BEGIN lazy-harness") == 1
    assert fake.content.count("# lazy-harness:qmd-sync") == 1


def test_an_empty_crontab_is_a_normal_state() -> None:
    """`crontab -l` exits non-zero with 'no crontab for user'. That is empty,
    not an error."""
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab()
    CronBackend(runner=fake).install(
        [SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")]
    )
    assert "# lazy-harness:qmd-sync" in fake.content


def test_uninstall_removes_only_the_managed_block() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab("0 4 * * * /home/me/backup.sh\n")
    backend = CronBackend(runner=fake)
    job = SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")
    backend.install([job])

    removed = backend.uninstall([job])

    assert removed == ["lazy-harness-qmd-sync"]
    assert fake.content.strip() == "0 4 * * * /home/me/backup.sh"


def test_discover_reports_the_declared_jobs() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab()
    backend = CronBackend(runner=fake)
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")])

    records = backend.discover()
    assert [r.name for r in records] == ["qmd-sync"]
    assert records[0].schedule == "0 */6 * * *"
    # cron has no liveness concept; presence in the crontab is a complete
    # answer to the question job_state asks.
    assert records[0].state is JobState.LOADED


def test_discover_is_unknown_when_crontab_is_absent() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    backend = CronBackend(runner=FakeCrontab(missing=True))
    state, detail = backend.job_state("lazy-harness-qmd-sync")
    assert state is JobState.UNKNOWN
    assert "crontab" in detail
    assert backend.discover() == []


def test_cron_backend_constructs_without_arguments() -> None:
    """Paired smoke test for the default runner."""
    from lazy_harness.scheduler.cron import CronBackend

    assert CronBackend()._runner is not None


def test_install_raises_when_the_crontab_write_is_rejected() -> None:
    """`_write` discarded the CompletedProcess, so a rejected write still
    printed a green tick per job with nothing installed."""
    import pytest

    from lazy_harness.scheduler.cron import CronBackend

    class Rejecting(FakeCrontab):
        def __call__(self, argv, *, input=None):  # noqa: A002
            if argv[1:] == ["-l"]:
                return super().__call__(argv)
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="errors in crontab file")

    with pytest.raises(RuntimeError, match="errors in crontab file"):
        CronBackend(runner=Rejecting()).install(
            [SchedulerJob(name="x", schedule="0 6 * * *", command="true")]
        )


def test_uninstall_preserves_the_path_install_computed(monkeypatch, tmp_path) -> None:
    """Re-deriving PATH on uninstall silently changes the surviving jobs.

    Run `lh scheduler uninstall` from inside a project venv and the untouched
    entries get a different PATH than the one `install` wrote.
    """
    from lazy_harness.scheduler.cron import CronBackend

    fake = FakeCrontab()
    backend = CronBackend(runner=fake)
    keep = SchedulerJob(name="keep", schedule="0 6 * * *", command="true")
    drop = SchedulerJob(name="drop", schedule="0 7 * * *", command="true")
    backend.install([keep, drop])

    original_path = next(
        line for line in fake.content.splitlines() if line.startswith("PATH=")
    )

    # Uninstall from a different environment, which is what running it from
    # inside a project venv looks like.
    other = tmp_path / "elsewhere" / "bin"
    other.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(other))
    backend.uninstall([drop])

    surviving = next(line for line in fake.content.splitlines() if line.startswith("PATH="))
    assert surviving == original_path
