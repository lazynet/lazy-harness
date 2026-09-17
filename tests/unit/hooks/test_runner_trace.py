"""`LH_HOOK_TRACE=1` records that a hook was dispatched, so silence means silence.

Every `pre_tool_use` builtin logs only when it has something to say —
`pre-tool-use-security` on a block, `-memory-size` and `-read-size` on a
warning, `-git-scope` never. So a hook that ran and *allowed* leaves no trace,
and the F9 gate's phase B could not tell it from a hook whose matcher group
Codex suppressed. Both readings came out as `the denied file was modified`, and
they have opposite fixes: one is the matcher, the other is the hook.

One line at the single dispatch point closes it. The properties that make it
worth having, each with a test below:

*   **Off unless explicitly on.** A line per tool call on every profile, forever,
    to serve a gate that runs a few times a year is not a trade worth making.
    Only the exact string `"1"` enables it.
*   **It fires before the builtin can fail.** A hook that ran and raised is a
    hook that ran; tracing after the decision would file it as never invoked —
    the same conflation this exists to remove.
*   **It never changes what the hook returns.** Auditing that can break a
    guardrail is worse than no auditing, which is the policy `_audit` in
    `pre_tool_use_security.py` already states.
*   **It does not collide with the block line.** The F9 gate counts
    `"<name>: blocked "` and `"<name>: invoked"` separately and subtracts one
    reading from the other; a trace that matched the block grep would report
    every dispatch as a denial.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent, HookOutput, Verdict
from lazy_harness.hooks import runner
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, BuiltinHookSpec

PRE_TOOL_USE = {
    "hook_event_name": "PreToolUse",
    "session_id": "s1",
    "cwd": "/tmp",
    "transcript_path": "/tmp/t.jsonl",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /"},
}

TRACE_VAR = "LH_HOOK_TRACE"


def register(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    main: object,
    *,
    blocking: bool = False,
) -> None:
    module_name = f"lazy_harness_trace_builtin_{name.replace('-', '_')}"
    module = types.ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        _BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name, blocking=blocking, event=None),
    )


PROFILES_SEEN: list[str] = []
"""Every profile `agent_dir_for` was asked about, per test.

A module-level list rather than an attribute on the `tmp_path`: `pathlib.Path`
defines `__slots__`, so `monkeypatch.setattr(tmp_path, ...)` raises rather than
recording anything, and the assertion it was meant to carry would never run.
"""


@pytest.fixture
def agent_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the trace's destination without touching a real profile.

    `agent_dir_for` is patched on the module the runner late-imports it from,
    which is the same indirection the builtins' own audit path uses.
    """
    import lazy_harness.hooks.builtins._shared as shared

    PROFILES_SEEN.clear()

    def fake(_cfg: object, profile: str) -> tuple[object, Path]:
        PROFILES_SEEN.append(profile)
        return object(), tmp_path

    monkeypatch.setattr(shared, "agent_dir_for", fake)
    return tmp_path


def _log_text(agent_dir: Path) -> str:
    log = agent_dir / "logs" / "hooks.log"
    return log.read_text(encoding="utf-8") if log.is_file() else ""


def _run(name: str = "guard", profile: str = "lazy") -> HookOutput:
    return runner.run_hook(name, profile=profile, stdin_text=json.dumps(PRE_TOOL_USE))


# --- the pair that makes the absence load-bearing --------------------------


def test_no_trace_is_written_when_the_variable_is_unset(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """Half of a pair — meaningless without the test below it."""
    monkeypatch.delenv(TRACE_VAR, raising=False)
    register(monkeypatch, "guard", lambda _event: HookDecision())

    _run()

    assert _log_text(agent_dir) == ""


def test_the_trace_is_written_when_the_variable_is_one(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """The half that makes the absence above evidence of the guard rather than
    of a destination the runner never reached."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(monkeypatch, "guard", lambda _event: HookDecision())

    _run()

    assert "guard: invoked" in _log_text(agent_dir)


@pytest.mark.parametrize("value", ["0", "", "yes", "true", "2", "on"])
def test_only_the_exact_string_one_enables_it(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path, value: str
) -> None:
    """A truthiness test would turn `LH_HOOK_TRACE=0` into tracing on."""
    monkeypatch.setenv(TRACE_VAR, value)
    register(monkeypatch, "guard", lambda _event: HookDecision())

    _run()

    assert _log_text(agent_dir) == ""


# --- what it must survive --------------------------------------------------


def test_a_hook_that_raises_is_still_recorded_as_invoked(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """A hook that ran and crashed is a hook that ran. Tracing after the
    decision would file it as never invoked — the exact conflation this
    exists to remove, reintroduced one layer down."""
    monkeypatch.setenv(TRACE_VAR, "1")

    def explode(_event: HookEvent) -> HookDecision:
        raise RuntimeError("boom")

    register(monkeypatch, "guard", explode, blocking=True)

    result = _run()

    assert "guard: invoked" in _log_text(agent_dir)
    assert result.exit_code == 2


def test_an_unparseable_payload_is_still_recorded_as_invoked(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """The dispatch happened; the payload is what failed."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(monkeypatch, "guard", lambda _event: HookDecision(), blocking=True)

    runner.run_hook("guard", profile="lazy", stdin_text="not json")

    assert "guard: invoked" in _log_text(agent_dir)


def test_a_denying_hook_writes_the_trace_as_well_as_its_own_line(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """Both counts grow on a denial, which is what makes `denied` and
    `fired-but-allowed` separable by subtraction in the gate."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(
        monkeypatch,
        "guard",
        lambda _event: HookDecision(verdict=Verdict.DENY, reason="no"),
        blocking=True,
    )

    result = _run()

    assert "guard: invoked" in _log_text(agent_dir)
    assert result.exit_code == 2


def test_an_unknown_hook_name_writes_no_trace(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """Nothing was invoked. Tracing here would report a hook that does not
    exist as having run, which is a worse answer than silence."""
    monkeypatch.setenv(TRACE_VAR, "1")

    result = runner.run_hook("no-such-hook", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert _log_text(agent_dir) == ""
    assert result.exit_code == 0


def test_a_failure_inside_the_trace_never_reaches_the_hooks_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Auditing must never keep the guardrail from firing — the policy
    `pre_tool_use_security.py::_audit` already states, applied here."""
    import lazy_harness.hooks.builtins._shared as shared

    def explode(_cfg: object, _profile: str) -> tuple[object, Path]:
        raise RuntimeError("no agent dir")

    monkeypatch.setattr(shared, "agent_dir_for", explode)
    monkeypatch.setenv(TRACE_VAR, "1")
    register(
        monkeypatch,
        "guard",
        lambda _event: HookDecision(verdict=Verdict.DENY, reason="no"),
        blocking=True,
    )

    result = _run()

    assert result.exit_code == 2
    assert result.stderr == "no"


# --- the two properties the F9 gate reads it through -----------------------


def test_the_trace_line_does_not_match_the_block_grep(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """`security_block_count` in the F9 gate greps `'<name>: blocked '`. A
    trace that matched it would report every dispatch as a denial and the
    phase would read `fired-but-allowed` on a turn nothing blocked."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(monkeypatch, "pre-tool-use-security", lambda _event: HookDecision())

    runner.run_hook("pre-tool-use-security", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert "pre-tool-use-security: blocked " not in _log_text(agent_dir)
    assert "pre-tool-use-security: invoked" in _log_text(agent_dir)


def test_the_trace_lands_under_the_profile_the_hook_ran_with(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """A hook invoked with `--profile lazy-codex` whose line landed in the
    global agent's log is the defect `agent_dir_for` was extracted after."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(monkeypatch, "guard", lambda _event: HookDecision())

    _run(profile="lazy-codex")

    assert PROFILES_SEEN == ["lazy-codex"]


def test_one_dispatch_writes_exactly_one_trace_line(
    monkeypatch: pytest.MonkeyPatch, agent_dir: Path
) -> None:
    """The gate reads a delta. Two lines per dispatch would double every count
    without changing any verdict, until a turn with one call read as two."""
    monkeypatch.setenv(TRACE_VAR, "1")
    register(monkeypatch, "guard", lambda _event: HookDecision())

    _run()

    assert _log_text(agent_dir).count("guard: invoked") == 1
