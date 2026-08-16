from __future__ import annotations

from click.testing import CliRunner

from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_cli() -> list[CheckResult]:
    """Verify all lh subcommands respond to --help without crashing."""
    # Imported here, not at module scope: `cli` pulls in `selftest_cmd`, which
    # imports this module back. At module scope whichever side was imported
    # first won, and importing this one first raised on a partial module.
    from lazy_harness.cli.main import cli

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
            results.append(CheckResult(group=group, name=f"{name}:help", status=CheckStatus.PASSED))
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
