from lazy_harness.selftest.result import CheckResult, CheckStatus, SelftestReport
from lazy_harness.selftest.runner import SelftestRunner


def test_runner_with_no_checks():
    runner = SelftestRunner(checks=[])
    report = runner.run()
    assert report.passed == 0
    assert report.failed == 0
    assert report.exit_code() == 0


def test_report_exit_code_with_failures():
    report = SelftestReport(
        results=[
            CheckResult(group="x", name="a", status=CheckStatus.FAILED, message="bad"),
        ]
    )
    assert report.exit_code() == 1


def test_report_exit_code_with_only_warnings():
    report = SelftestReport(
        results=[
            CheckResult(group="x", name="a", status=CheckStatus.WARNING, message="meh"),
        ]
    )
    assert report.exit_code() == 0


def test_runner_catches_check_exceptions():
    def bad_check():
        raise RuntimeError("boom")

    runner = SelftestRunner(checks=[bad_check])
    report = runner.run()
    assert report.failed >= 1
    assert any("boom" in r.message for r in report.results)
