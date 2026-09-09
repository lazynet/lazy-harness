"""run_inference — the single inference resolution seam (ADR-039)."""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, LLMBackendConfig, LLMConfig
from lazy_harness.llm.base import LLMBackendError


class _StubBackend:
    """In-memory backend. Records what it was asked, returns what it was given."""

    def __init__(self, answer: str = "ok", raises: Exception | None = None) -> None:
        self._answer = answer
        self._raises = raises
        self.calls: list[dict] = []

    @property
    def name(self) -> str:
        return "stub"

    def default_model(self) -> str:
        return "stub-default"

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        self.calls.append({"prompt": prompt, "model": model, "schema": schema})
        if self._raises is not None:
            raise self._raises
        return self._answer


def _cfg() -> Config:
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        roles={"classify": "local"},
    )
    return cfg


def _patch_backend(monkeypatch: pytest.MonkeyPatch, backend: object) -> list[dict]:
    """Replace backend construction, recording every build request."""
    from lazy_harness.llm import invoke as mod

    built: list[dict] = []

    def fake_build(**kwargs):  # noqa: ANN003
        built.append(kwargs)
        return backend

    monkeypatch.setattr(mod, "build_backend", fake_build)
    return built


def test_success_returns_output_and_no_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend("the answer"))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5)
    assert r.success is True
    assert r.output == "the answer"
    assert r.error is None
    assert r.backend == "ollama"
    assert r.model == "qwen2.5-coder:7b"


def test_never_raises_on_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend(raises=LLMBackendError("connection refused")))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5)
    assert r.success is False
    assert r.error is not None
    assert r.error.kind == "backend-unreachable"
    assert "connection refused" in r.error.message


def test_empty_output_is_its_own_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend(""))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5)
    assert r.error is not None
    assert r.error.kind == "empty"
    assert r.output == ""


def test_schema_violation_when_a_value_is_outside_its_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured failure: a 7B model answering "bug" against an enum that
    does not contain it, while emitting well-formed JSON."""
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend('{"kind": "bug"}'))
    schema = {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["debug", "docs"]}},
        "required": ["kind"],
    }
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema=schema)
    assert r.error is not None
    assert r.error.kind == "schema-violation"
    assert "bug" in r.error.message


def test_schema_violation_when_a_required_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend('{"other": 1}'))
    schema = {"type": "object", "required": ["kind"]}
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema=schema)
    assert r.error is not None
    assert r.error.kind == "schema-violation"


def test_valid_against_schema_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend('{"kind": "debug"}'))
    schema = {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["debug", "docs"]}},
        "required": ["kind"],
    }
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema=schema)
    assert r.success is True


def test_unparseable_json_under_a_schema_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend("not json at all"))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema={"type": "object"})
    assert r.error is not None
    assert r.error.kind == "schema-violation"


def test_output_is_a_string_on_every_failure_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract promises a string, never null, on every path."""
    from lazy_harness.llm.invoke import run_inference

    cases = [
        (_StubBackend(raises=LLMBackendError("refused")), None),
        (_StubBackend(""), None),
        (_StubBackend("nope"), {"type": "object"}),
    ]
    for backend, schema in cases:
        _patch_backend(monkeypatch, backend)
        r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema=schema)
        assert isinstance(r.output, str)


def test_unknown_role_is_reported_not_raised() -> None:
    from lazy_harness.llm.invoke import run_inference

    r = run_inference("p", role="nope", cfg=Config(), timeout=5)
    assert r.success is False
    assert r.error is not None
    assert r.error.kind == "backend-unreachable"


def test_kinds_are_exhaustive() -> None:
    from lazy_harness.llm.invoke import INFERENCE_KINDS

    assert INFERENCE_KINDS == (
        "backend-unreachable",
        "timeout",
        "schema-violation",
        "empty",
        "backend-error",
    )


def test_a_failing_role_never_falls_back_to_another_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silent fall-through to a billed model is how a cost optimisation
    becomes a cost surprise. Assert the second backend is never constructed,
    not merely that the result reports failure."""
    from lazy_harness.llm.invoke import run_inference

    cfg = _cfg()
    cfg.llm.backends["haiku"] = LLMBackendConfig(type="claude", model="haiku")
    cfg.llm.roles["distill"] = "haiku"

    built = _patch_backend(monkeypatch, _StubBackend(raises=LLMBackendError("down")))
    r = run_inference("p", role="classify", cfg=cfg, timeout=5)

    assert r.success is False
    assert len(built) == 1
    assert built[0]["type"] == "ollama"


def test_schema_is_forwarded_to_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    backend = _StubBackend('{"kind": "debug"}')
    _patch_backend(monkeypatch, backend)
    schema = {"type": "object"}
    run_inference("p", role="classify", cfg=_cfg(), timeout=5, schema=schema)
    assert backend.calls[0]["schema"] == schema


def test_model_falls_back_to_the_backend_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm.invoke import run_inference

    cfg = Config()
    cfg.llm = LLMConfig(
        backends={"local": LLMBackendConfig(type="ollama")}, roles={"classify": "local"}
    )
    backend = _StubBackend("ok")
    _patch_backend(monkeypatch, backend)
    r = run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert r.model == "stub-default"
    assert backend.calls[0]["model"] == "stub-default"


def test_api_key_env_is_resolved_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    monkeypatch.setenv("SOME_LLM_KEY", "sk-secret")
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={
            "r": LLMBackendConfig(
                type="openai-compatible",
                base_url="http://x",
                api_key_env="SOME_LLM_KEY",
            )
        },
        roles={"classify": "r"},
    )
    built = _patch_backend(monkeypatch, _StubBackend("ok"))
    run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert built[0]["api_key"] == "sk-secret"


def test_missing_api_key_env_does_not_leak_the_variable_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm.invoke import run_inference

    monkeypatch.delenv("SOME_LLM_KEY", raising=False)
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={
            "r": LLMBackendConfig(
                type="openai-compatible", base_url="http://x", api_key_env="SOME_LLM_KEY"
            )
        },
        roles={"classify": "r"},
    )
    built = _patch_backend(monkeypatch, _StubBackend("ok"))
    run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert built[0]["api_key"] == ""


def test_duration_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend("ok"))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5)
    assert isinstance(r.duration_ms, int)
    assert r.duration_ms >= 0


def test_typed_timeout_maps_to_the_timeout_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Carried by the exception type, not by sniffing its message: an httpx
    read timeout stringifies to "" and would otherwise be misreported as
    backend-unreachable, taking exit 70 instead of the contracted 124."""
    from lazy_harness.llm.base import LLMTimeoutError
    from lazy_harness.llm.invoke import run_inference

    _patch_backend(monkeypatch, _StubBackend(raises=LLMTimeoutError("")))
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5)
    assert r.error is not None
    assert r.error.kind == "timeout"


def test_model_override_replaces_the_resolved_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller-supplied model (e.g. `lh memory consolidate --model`) wins over
    the role's configured model, without changing which backend answers."""
    from lazy_harness.llm.invoke import run_inference

    backend = _StubBackend("ok")
    _patch_backend(monkeypatch, backend)
    r = run_inference("p", role="classify", cfg=_cfg(), timeout=5, model="override-model")
    assert r.model == "override-model"
    assert backend.calls[0]["model"] == "override-model"
