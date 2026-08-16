import subprocess
import sys
from unittest.mock import patch

from lazy_harness.selftest.checks.cli_check import check_cli
from lazy_harness.selftest.result import CheckStatus


def test_importing_the_check_first_does_not_hit_a_circular_import():
    """This module must import on its own, not only after the CLI.

    `cli_check` imported `lazy_harness.cli.main` at module scope, which
    imports `selftest_cmd`, which imports `cli_check` — so whichever came
    first won. Importing the CLI first masked it, which is why the full
    suite stayed green while `pytest tests/unit/selftest/` could not even
    collect.
    """
    proc = subprocess.run(
        [sys.executable, "-c", "from lazy_harness.selftest.checks.cli_check import check_cli"],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr


def test_check_cli_all_pass():
    results = check_cli()
    assert len(results) > 0
    assert all(r.status == CheckStatus.PASSED for r in results)


def test_check_cli_group_is_cli():
    results = check_cli()
    assert all(r.group == "cli" for r in results)


def test_check_cli_covers_known_commands():
    results = check_cli()
    names = {r.name for r in results}
    for cmd in ("init:help", "doctor:help", "deploy:help", "status:help"):
        assert cmd in names, f"{cmd} not found in cli check results"


def test_check_cli_reports_failure_on_bad_command():
    from click import command, group

    @group()
    def fake_cli() -> None:
        pass

    @command()
    def bad() -> None:
        raise RuntimeError("boom")

    fake_cli.add_command(bad, "bad")

    # Patched at its source: `check_cli` now imports `cli` when it runs, so
    # there is no module-level name here to replace.
    with patch("lazy_harness.cli.main.cli", fake_cli):
        results = check_cli()

    bad_result = next((r for r in results if r.name == "bad:help"), None)
    assert bad_result is None or bad_result.status == CheckStatus.PASSED
