from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class CheckResult:
    group: str
    name: str
    status: CheckStatus
    message: str = ""


@dataclass
class SelftestReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.FAILED)

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.WARNING)

    def exit_code(self) -> int:
        return 1 if self.failed > 0 else 0
