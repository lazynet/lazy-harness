from __future__ import annotations

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_cli() -> list[CheckResult]:
    """Verify all lh subcommands respond to --help without crashing."""
    results: list[CheckResult] = []
    group = "cli"
    runner = CliRunner()

    root_result = runner.invoke(cli, ["--help"])
    if root_result.exit_code == 0:
        results.append(CheckResult(group=group, name="lh:help", status=CheckStatus.PASSED))
    else:
        results.append(
            CheckResult(
                group=group,
                name="lh:help",
                status=CheckStatus.FAILED,
                message=root_result.output[:200],
            )
        )

    for name in sorted(cli.commands):
        result = runner.invoke(cli, [name, "--help"])
        if result.exit_code == 0:
            results.append(
                CheckResult(group=group, name=f"{name}:help", status=CheckStatus.PASSED)
            )
        else:
            results.append(
                CheckResult(
                    group=group,
                    name=f"{name}:help",
                    status=CheckStatus.FAILED,
                    message=result.output[:200],
                )
            )

    return results
