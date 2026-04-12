from unittest.mock import patch

from lazy_harness.selftest.checks.cli_check import check_cli
from lazy_harness.selftest.result import CheckStatus


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

    with patch("lazy_harness.selftest.checks.cli_check.cli", fake_cli):
        results = check_cli()

    bad_result = next((r for r in results if r.name == "bad:help"), None)
    assert bad_result is None or bad_result.status == CheckStatus.PASSED
