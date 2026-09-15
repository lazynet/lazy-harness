"""Tests for the loop-events post-release check.

This check exists because unit tests alone shipped two attribution bugs to a
release: they exercised the hooks as imported functions, never as the command
the agent actually runs. So it drives the real hooks in a subprocess against a
throwaway repo and reads back what they wrote.

The seam these tests inject at used to be `hooks_dir`, a directory of hook
*scripts*. Both hooks the check drives are migrated now, and a migrated builtin
is not a script — it is reached through `lh hook <name> --profile`, which
resolves the module from the installed package and never consults a directory.
So the override moved one level up, from *where the script is* to *how the hook
is run*, which is the only thing left that a test can stand in for.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.selftest.result import CheckStatus


def _statuses(results: list) -> dict[str, CheckStatus]:
    return {r.name: r.status for r in results}


def test_passes_against_the_installed_hooks() -> None:
    """Parameter-less smoke run: exercises the real `lh hook` invocation.

    A check that is only ever called with an injected invoker leaves the path
    `lh selftest` actually takes completely untested.
    """
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    results = check_loop_events()

    assert results, "the check must report something"
    assert all(r.status == CheckStatus.PASSED for r in results), _statuses(results)


def _record_the_raw_cwd(name: str, payload: dict[str, str], env: dict[str, str]) -> str:
    """The pre-fix hook: stores the cwd verbatim instead of the repo that owns it.

    Writes through `MetricsDB` rather than raw SQL so this stand-in cannot
    drift from the schema the check reads back, which would make it fail for a
    reason that has nothing to do with attribution.
    """
    from lazy_harness.core.config import load_config
    from lazy_harness.monitoring.db import MetricsDB

    cfg = load_config(Path(env["LH_CONFIG_DIR"]) / "config.toml")
    kind = "nontrivial_prompt" if name == "user-prompt-goal" else "session_closed"
    db = MetricsDB(cfg.monitoring.db)
    try:
        db.record_loop_event(
            session=payload.get("session_id", ""),
            kind=kind,
            project=payload.get("cwd", ""),
            profile="",
        )
    finally:
        db.close()
    return ""


def test_reports_the_subdirectory_check_failed_when_a_hook_records_the_raw_cwd() -> None:
    """Prove the check can fail — a green that cannot go red proves nothing."""
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    results = check_loop_events(invoke=_record_the_raw_cwd)

    statuses = _statuses(results)
    assert statuses["project-from-subdirectory"] == CheckStatus.FAILED, statuses


def test_reports_failed_when_the_hook_cannot_be_invoked() -> None:
    """A hook that did not run must be reported, never treated as a silent pass."""
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    def _cannot_run(name: str, payload: dict[str, str], env: dict[str, str]) -> str:
        return f"{name} could not be invoked"

    results = check_loop_events(invoke=_cannot_run)

    assert any(r.status == CheckStatus.FAILED for r in results), _statuses(results)


def test_the_injected_invoker_receives_the_probe_repo_and_its_environment() -> None:
    """The seam must hand over what the real invocation gets, or it proves nothing.

    Without this, an override that silently received an empty payload would
    still let the red test above go red — for the wrong reason.
    """
    from lazy_harness.selftest.checks.loop_events_check import check_loop_events

    seen: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def _record(name: str, payload: dict[str, str], env: dict[str, str]) -> str:
        seen.append((name, dict(payload), dict(env)))
        return ""

    check_loop_events(invoke=_record)

    assert [name for name, _, _ in seen] == [
        "user-prompt-goal",
        "user-prompt-goal",
        "session-end",
    ]
    assert all("session_id" in payload for _, payload, _ in seen)
    assert all("LH_CONFIG_DIR" in env for _, _, env in seen)
    # The two prompt payloads must name *different* directories: one an
    # artifact subdirectory, one a linked worktree. A probe that fed the same
    # cwd twice would report both attribution rules green on one of them.
    assert seen[0][1]["cwd"] != seen[1][1]["cwd"]
    assert json.dumps(seen[0][1])  # payloads stay JSON-serialisable for the real path
