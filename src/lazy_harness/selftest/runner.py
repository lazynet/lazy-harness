from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from lazy_harness.selftest.result import CheckResult, CheckStatus, SelftestReport

CheckFunc = Callable[[], list[CheckResult]]


@dataclass
class SelftestRunner:
    checks: list[CheckFunc] = field(default_factory=list)

    def run(self) -> SelftestReport:
        report = SelftestReport()
        for check in self.checks:
            try:
                results = check()
            except Exception as e:  # noqa: BLE001
                name = getattr(check, "__name__", "unknown")
                results = [
                    CheckResult(
                        group=name,
                        name="check-error",
                        status=CheckStatus.FAILED,
                        message=f"check raised: {e}",
                    )
                ]
            report.results.extend(results)
        return report
