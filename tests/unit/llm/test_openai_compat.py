"""OpenAICompatibleBackend — /v1/chat/completions over httpx (ADR-033)."""

from __future__ import annotations

import httpx
import pytest


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("POST", "http://test"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> object:
        return self._payload


_OK_PAYLOAD = {"choices": [{"message": {"content": "local answer"}}]}


def test_openai_compatible_backend_satisfies_protocol() -> None:
    from lazy_harness.llm.base import LLMBackend
    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend

    assert isinstance(OpenAICompatibleBackend(base_url="http://localhost:11434"), LLMBackend)


def test_name_and_default_model() -> None:
    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend

    backend = OpenAICompatibleBackend(base_url="http://localhost:11434")
    assert backend.name == "openai-compatible"
    assert backend.default_model() == "llama3.2:3b"


def test_complete_posts_openai_wire_format_and_returns_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm import openai_compat as mod

    captured: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001, ANN003 — mirrors httpx.post
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")
        return _FakeResponse(_OK_PAYLOAD)

    monkeypatch.setattr(mod.httpx, "post", fake_post)

    backend = mod.OpenAICompatibleBackend(base_url="http://localhost:11434/", api_key="sk-x")
    result = backend.complete("hello", "llama3.2:3b", 30)

    assert result == "local answer"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"] == {
        "model": "llama3.2:3b",
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert captured["headers"] == {"Authorization": "Bearer sk-x"}
    assert captured["timeout"] == 30


def test_api_key_defaults_to_none_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import openai_compat as mod

    captured: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001, ANN003
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse(_OK_PAYLOAD)

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    mod.OpenAICompatibleBackend(base_url="http://localhost:8080").complete("p", "m", 1)
    assert captured["headers"] == {"Authorization": "Bearer none"}


def test_connection_error_maps_to_llm_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import openai_compat as mod
    from lazy_harness.llm.base import LLMBackendError

    def fake_post(url, **kwargs):  # noqa: ANN001, ANN003
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    backend = mod.OpenAICompatibleBackend(base_url="http://localhost:11434")
    with pytest.raises(LLMBackendError):
        backend.complete("p", "m", 1)


def test_non_200_maps_to_llm_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import openai_compat as mod
    from lazy_harness.llm.base import LLMBackendError

    monkeypatch.setattr(mod.httpx, "post", lambda url, **kw: _FakeResponse({}, status_code=500))
    backend = mod.OpenAICompatibleBackend(base_url="http://localhost:11434")
    with pytest.raises(LLMBackendError):
        backend.complete("p", "m", 1)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"no_message": True}]},
    ],
)
def test_malformed_response_maps_to_llm_backend_error(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    from lazy_harness.llm import openai_compat as mod
    from lazy_harness.llm.base import LLMBackendError

    monkeypatch.setattr(mod.httpx, "post", lambda url, **kw: _FakeResponse(payload))
    backend = mod.OpenAICompatibleBackend(base_url="http://localhost:11434")
    with pytest.raises(LLMBackendError):
        backend.complete("p", "m", 1)
