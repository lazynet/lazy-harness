from __future__ import annotations

import json as json_lib

import click
from rich.console import Console

from lazy_harness.core.paths import config_file
from lazy_harness.selftest.checks.cli_check import check_cli
from lazy_harness.selftest.checks.config_check import check_config
from lazy_harness.selftest.checks.hooks_check import check_hooks
from lazy_harness.selftest.checks.knowledge_check import check_knowledge
from lazy_harness.selftest.checks.monitoring_check import check_monitoring
from lazy_harness.selftest.checks.profile_check import check_profiles
from lazy_harness.selftest.checks.scheduler_check import check_scheduler
from lazy_harness.selftest.result import CheckStatus
from lazy_harness.selftest.runner import SelftestRunner


@click.command("selftest")
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
@click.option("--fix", is_flag=True, help="Attempt to repair fixable issues.")
def selftest(as_json: bool, fix: bool) -> None:
    """Validate the lazy-harness installation end-to-end."""
    cfg_path = config_file()
    runner = SelftestRunner(
        checks=[
            lambda: check_config(config_path=cfg_path),
            lambda: check_profiles(config_path=cfg_path),
            lambda: check_hooks(config_path=cfg_path),
            lambda: check_monitoring(config_path=cfg_path),
            lambda: check_knowledge(config_path=cfg_path),
            lambda: check_scheduler(config_path=cfg_path),
            lambda: check_cli(),
        ]
    )
    report = runner.run()

    if as_json:
        click.echo(
            json_lib.dumps(
                {
                    "results": [
                        {
                            "group": r.group,
                            "name": r.name,
                            "status": r.status.value,
                            "message": r.message,
                        }
                        for r in report.results
                    ],
                    "passed": report.passed,
                    "failed": report.failed,
                    "warnings": report.warnings,
                },
                indent=2,
            )
        )
        raise SystemExit(report.exit_code())

    console = Console()
    by_group: dict[str, list] = {}
    for r in report.results:
        by_group.setdefault(r.group, []).append(r)
    for group, results in by_group.items():
        passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
        total = len(results)
        all_pass = passed == total
        marker = "✓" if all_pass else "✗"
        console.print(f"{group:20s} {marker} ({passed}/{total})")
        for r in results:
            if r.status != CheckStatus.PASSED:
                m = "✗" if r.status == CheckStatus.FAILED else "⚠"
                console.print(f"  {m} {r.name}: {r.message}")

    console.print()
    console.print(
        f"Summary: {report.passed} passed, {report.failed} failed, {report.warnings} warnings"
    )
    raise SystemExit(report.exit_code())
