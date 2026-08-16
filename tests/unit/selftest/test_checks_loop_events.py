"""Tests for the loop-events post-release check.

This check exists because unit tests alone shipped two attribution bugs to a
release: they exercised the hooks as imported functions, never as the scripts
the agent actually runs. So it drives the real hook files in a subprocess
against a throwaway repo and reads back what they wrote.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.selftest.result import CheckStatus


def _statuses(results: list) -> dict[str, CheckStatus]:
    return {r.name: r.status for r in results}


def test_passes_against_the_installed_hooks() -> None:
    """Parameter-less smoke run: exercises the default hooks-dir resolution.

    A check that is only ever called with an explicit directory leaves the
    path `lh selftest` actually takes completely untested.
    """
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    results = check_loop_events()

    assert results, "the check must report something"
    assert all(r.status == CheckStatus.PASSED for r in results), _statuses(results)


def test_reports_the_subdirectory_check_failed_when_a_hook_records_the_raw_cwd(
    tmp_path: Path,
) -> None:
    """Prove the check can fail — a green that cannot go red proves nothing."""
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    hooks = tmp_path / "broken"
    hooks.mkdir()
    # The pre-fix hook: stores the cwd verbatim instead of the repo that owns it.
    (hooks / "user_prompt_goal.py").write_text(
        "import json, sys\n"
        "from lazy_harness.monitoring.db import MetricsDB, resolve_db_path\n"
        "payload = json.load(sys.stdin)\n"
        "MetricsDB(resolve_db_path()).record_loop_event(\n"
        "    session=payload.get('session_id', ''),\n"
        "    kind='nontrivial_prompt',\n"
        "    project=payload.get('cwd', ''),\n"
        ")\n"
        "sys.exit(0)\n"
    )
    (hooks / "session_end.py").write_text(
        "import json, sys\n"
        "from lazy_harness.monitoring.db import MetricsDB, resolve_db_path\n"
        "payload = json.load(sys.stdin)\n"
        "MetricsDB(resolve_db_path()).record_loop_event(\n"
        "    session=payload.get('session_id', ''),\n"
        "    kind='session_closed',\n"
        "    project=payload.get('cwd', ''),\n"
        ")\n"
        "sys.exit(0)\n"
    )

    results = check_loop_events(hooks_dir=hooks)

    statuses = _statuses(results)
    assert statuses["project-from-subdirectory"] == CheckStatus.FAILED, statuses


def test_reports_failed_when_the_hook_file_is_missing(tmp_path: Path) -> None:
    """A missing hook must be reported, never treated as a silent pass."""
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    results = check_loop_events(hooks_dir=tmp_path)

    assert any(r.status == CheckStatus.FAILED for r in results), _statuses(results)
