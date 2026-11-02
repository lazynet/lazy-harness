"""ClaudeBackend — headless `claude -p` call, isolated from the profile (ADR-033)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

#: Real `claude -p --output-format json --setting-sources "" --no-session-persistence`
#: stdout, 2.1.316, 2026-11-01 (`specs/designs/claude-code-evidence.md`, run i).
_PROBE = Path(__file__).parents[2] / "fixtures" / "claude-p-json-result.json"


class _FakeCompleted:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_claude_backend_satisfies_protocol() -> None:
    from lazy_harness.llm.base import LLMBackend
    from lazy_harness.llm.claude import ClaudeBackend

    assert isinstance(ClaudeBackend(), LLMBackend)


def test_name_and_default_model() -> None:
    from lazy_harness.llm.claude import ClaudeBackend

    backend = ClaudeBackend()
    assert backend.name == "claude"
    assert backend.default_model() == "claude-haiku-4-5-20251001"


def test_complete_runs_claude_subprocess_isolated_from_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--setting-sources ""` stops every hook, plugin hooks included, and
    `--no-session-persistence` stops the transcript under `projects/` that
    ingest, export and the compound loop would read as a user session
    (`specs/designs/claude-code-evidence.md`, 2026-11-01)."""
    from lazy_harness.llm import claude as claude_mod

    captured: dict = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003 — mirrors subprocess.run
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        captured["timeout"] = kwargs.get("timeout")
        captured["capture_output"] = kwargs.get("capture_output")
        captured["text"] = kwargs.get("text")
        return _FakeCompleted("  the answer \n")

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)

    result = claude_mod.ClaudeBackend().complete("hello", "test-model", 42)

    assert result == "the answer"
    assert captured["argv"] == [
        "claude",
        "-p",
        "--model",
        "test-model",
        "--output-format",
        "json",
        "--setting-sources",
        "",
        "--no-session-persistence",
    ]
    assert captured["input"] == "hello"
    assert captured["timeout"] == 42
    assert captured["capture_output"] is True
    assert captured["text"] is True


def test_complete_empty_stdout_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import claude as claude_mod

    monkeypatch.setattr(claude_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted("   \n"))
    assert claude_mod.ClaudeBackend().complete("p", "m", 1) == ""


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired(cmd="claude", timeout=1),
        FileNotFoundError("claude not on PATH"),
        OSError("boom"),
    ],
)
def test_complete_maps_subprocess_failures_to_llm_backend_error(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    from lazy_harness.llm import claude as claude_mod
    from lazy_harness.llm.base import LLMBackendError

    def fake_run(*a, **kw):  # noqa: ANN002, ANN003
        raise exc

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)
    with pytest.raises(LLMBackendError):
        claude_mod.ClaudeBackend().complete("p", "m", 1)


def test_complete_nonzero_exit_raises_with_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import claude as claude_mod
    from lazy_harness.llm.base import LLMBackendError

    monkeypatch.setattr(
        claude_mod.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted("", returncode=1, stderr="invalid api key\n"),
    )
    with pytest.raises(LLMBackendError, match="invalid api key"):
        claude_mod.ClaudeBackend().complete("p", "m", 1)


def test_complete_nonzero_exit_without_stderr_reports_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm import claude as claude_mod
    from lazy_harness.llm.base import LLMBackendError

    monkeypatch.setattr(
        claude_mod.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted("", returncode=2, stderr="  \n"),
    )
    with pytest.raises(LLMBackendError, match="claude exited 2"):
        claude_mod.ClaudeBackend().complete("p", "m", 1)


def test_claude_accepts_and_ignores_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """`claude -p` has no structured-output flag, so the argv must not grow one.
    Callers keep the lenient parse_response fallback for this backend."""
    from lazy_harness.llm import claude as mod

    captured: dict = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        captured["argv"] = argv
        return _FakeCompleted("{}", returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = mod.ClaudeBackend().complete("p", "m", 5, schema={"type": "object"})

    assert out == "{}"
    joined = " ".join(captured["argv"])
    assert "schema" not in joined
    assert "response-format" not in joined


def test_subprocess_timeout_raises_a_typed_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from lazy_harness.llm import claude as mod
    from lazy_harness.llm.base import LLMTimeoutError

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(LLMTimeoutError):
        mod.ClaudeBackend().complete("p", "m", 5)


def _probe_stdout(**overrides: object) -> str:
    data = json.loads(_PROBE.read_text())
    data.update(overrides)
    return json.dumps(data)


def test_complete_returns_the_result_text_of_the_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`parse_response` must see exactly the text the model wrote, as it did
    under `--output-format text`, not the envelope around it."""
    from lazy_harness.llm import claude as mod

    stdout = _probe_stdout(result="  {\"decisions\": []}\n")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout))

    assert mod.ClaudeBackend().complete("p", "m", 5) == '{"decisions": []}'


def test_complete_with_usage_reports_per_model_tokens_and_the_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm import claude as mod
    from lazy_harness.llm.base import ModelUsage

    stdout = _PROBE.read_text()
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout))

    completion = mod.ClaudeBackend().complete_with_usage("p", "m", 5)

    assert completion.text == "OK"
    assert completion.session_id == "bbe45a2d-ae50-4c2a-893b-005282f8bb59"
    assert completion.service_tier == "standard"
    # The 1-hour cache write bills at 2x base input against the 5-minute
    # write's 1.25x (ADR-065), so the two stay split as the transcript reader
    # keeps them.
    assert completion.usage == (
        ModelUsage(
            model="claude-haiku-4-5-20251001",
            input_tokens=9,
            output_tokens=66,
            cache_read_tokens=14595,
            cache_creation_tokens=0,
            cache_creation_1h_tokens=8386,
            cost_usd=0.0185705,
        ),
    )


def test_an_error_envelope_with_exit_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error text sits in `result`; returned as an evaluation it would be
    parsed as the model's answer."""
    from lazy_harness.llm import claude as mod
    from lazy_harness.llm.base import LLMBackendError

    stdout = _probe_stdout(is_error=True, subtype="error_during_execution", result="overloaded")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout))

    with pytest.raises(LLMBackendError, match="overloaded"):
        mod.ClaudeBackend().complete("p", "m", 5)


def test_stdout_that_is_not_an_envelope_is_returned_as_text_with_no_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm import claude as mod

    monkeypatch.setattr(
        mod.subprocess, "run", lambda *a, **kw: _FakeCompleted("  plain words \n")
    )

    completion = mod.ClaudeBackend().complete_with_usage("p", "m", 5)

    assert completion.text == "plain words"
    assert completion.usage == ()
    assert completion.session_id is None


def test_claude_backend_reports_usage() -> None:
    from lazy_harness.llm.base import UsageReportingBackend
    from lazy_harness.llm.claude import ClaudeBackend

    assert isinstance(ClaudeBackend(), UsageReportingBackend)


def test_both_cache_write_ttls_are_read_from_their_own_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe wrote only 1-hour cache, so its 1h figure equals the total;
    distinct values catch a parser that reads the total for either half."""
    from lazy_harness.llm import claude as mod

    data = json.loads(_PROBE.read_text())
    row = data["modelUsage"]["claude-haiku-4-5-20251001"]
    row.update(
        cacheCreationInputTokens=700,
        cacheCreationEphemeral5mInputTokens=300,
        cacheCreationEphemeral1hInputTokens=400,
    )
    stdout = json.dumps(data)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout))

    (usage,) = mod.ClaudeBackend().complete_with_usage("p", "m", 5).usage

    assert (usage.cache_creation_tokens, usage.cache_creation_1h_tokens) == (300, 400)


def test_usage_agrees_with_the_lh_exec_parser_of_the_same_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two parsers read one `claude -p` JSON envelope: this backend's and
    `ClaudeCodeAdapter.parse_headless_result` behind `lh exec`. They must not
    give two answers for the same call."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.llm import claude as mod

    stdout = _PROBE.read_text()
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout))

    completion = mod.ClaudeBackend().complete_with_usage("p", "m", 5)
    headless = ClaudeCodeAdapter().parse_headless_result(stdout, 0)

    (usage,) = completion.usage
    assert completion.text == headless.output
    assert completion.session_id == headless.session_id
    assert usage.output_tokens == headless.output_tokens
    assert usage.cache_read_tokens == headless.cache_read_tokens
    assert (
        usage.cache_creation_tokens + usage.cache_creation_1h_tokens
        == headless.cache_creation_tokens
    )
    assert (
        usage.input_tokens
        + usage.cache_read_tokens
        + usage.cache_creation_tokens
        + usage.cache_creation_1h_tokens
        == headless.prompt_tokens
    )
    assert usage.cost_usd == headless.cost_usd
