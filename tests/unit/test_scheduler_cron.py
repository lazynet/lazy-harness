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
    # cron job fails. Compared against the value rather than the prefix: a
    # substring check passes on `PATH=` followed by nothing at all.
    from lazy_harness.scheduler.paths import resolved_path

    assert f"PATH={resolved_path()}" in fake.content


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

    Removing one job must not rewrite the others' environment. The block may
    carry a PATH written by an older version of this tool — which is exactly
    the case on any machine upgrading past the resolver change — and that is
    the user's installed state, not something an uninstall gets to revise.
    """
    from lazy_harness.scheduler.cron import CronBackend
    from lazy_harness.scheduler.paths import resolved_path

    fake = FakeCrontab()
    backend = CronBackend(runner=fake)
    keep = SchedulerJob(name="keep", schedule="0 6 * * *", command="true")
    drop = SchedulerJob(name="drop", schedule="0 7 * * *", command="true")
    backend.install([keep, drop])

    # Rewrite the block's PATH to something this machine would never derive.
    # Setting `$PATH` no longer works as the lever: `resolved_path` is built
    # from the platform, so it returns the same string before and after, and a
    # backend that re-derived on every uninstall would pass unnoticed.
    written = fake.content.replace(f"PATH={resolved_path()}", "PATH=/opt/pinned/bin")
    assert written != fake.content, "the install did not write the PATH this test rewrites"
    fake.content = written

    backend.uninstall([drop])

    surviving = next(line for line in fake.content.splitlines() if line.startswith("PATH="))
    assert surviving == "PATH=/opt/pinned/bin"
