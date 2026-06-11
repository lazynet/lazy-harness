"""Backend registry — alias resolution per the ADR-033 table."""

from __future__ import annotations

import pytest

from lazy_harness.core.config import CompoundLoopConfig

KNOWN_BACKENDS = ["claude", "ollama", "mlx", "openai-compatible"]


def _cfg(backend: str, options: dict[str, str] | None = None) -> CompoundLoopConfig:
    return CompoundLoopConfig(backend=backend, backend_options=options or {})


@pytest.mark.parametrize("name", KNOWN_BACKENDS)
def test_every_registered_backend_satisfies_protocol(name: str) -> None:
    from lazy_harness.llm.base import LLMBackend
    from lazy_harness.llm.registry import get_backend

    options = {"base_url": "http://gpu:11434"} if name == "openai-compatible" else {}
    backend = get_backend(_cfg(name, options))
    assert isinstance(backend, LLMBackend), f"{name!r} backend does not satisfy LLMBackend"


def test_claude_resolves_to_claude_backend() -> None:
    from lazy_harness.llm.claude import ClaudeBackend
    from lazy_harness.llm.registry import get_backend

    assert isinstance(get_backend(_cfg("claude")), ClaudeBackend)


def test_ollama_alias_presets_localhost_11434() -> None:
    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend
    from lazy_harness.llm.registry import get_backend

    backend = get_backend(_cfg("ollama"))
    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend._base_url == "http://localhost:11434"


def test_mlx_alias_presets_localhost_8080() -> None:
    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend
    from lazy_harness.llm.registry import get_backend

    backend = get_backend(_cfg("mlx"))
    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend._base_url == "http://localhost:8080"


def test_base_url_option_overrides_alias_default() -> None:
    from lazy_harness.llm.registry import get_backend

    backend = get_backend(_cfg("ollama", {"base_url": "http://my-gpu-box:11434"}))
    assert backend._base_url == "http://my-gpu-box:11434"


def test_api_key_option_is_passed_through() -> None:
    from lazy_harness.llm.registry import get_backend

    backend = get_backend(_cfg("ollama", {"api_key": "sk-secret"}))
    assert backend._api_key == "sk-secret"


def test_openai_compatible_requires_base_url() -> None:
    from lazy_harness.llm.base import LLMBackendError
    from lazy_harness.llm.registry import get_backend

    with pytest.raises(LLMBackendError, match="base_url"):
        get_backend(_cfg("openai-compatible"))


def test_unknown_backend_raises_not_found_with_available_list() -> None:
    from lazy_harness.llm.registry import LLMBackendNotFoundError, get_backend

    with pytest.raises(LLMBackendNotFoundError) as excinfo:
        get_backend(_cfg("bedrock"))
    msg = str(excinfo.value)
    assert "bedrock" in msg
    for name in KNOWN_BACKENDS:
        assert name in msg


def test_ollama_config_to_invoke_llm_end_to_end_without_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-033 acceptance: backend="ollama" → OpenAICompatibleBackend at
    localhost:11434 → invoke_llm posts /v1/chat/completions and returns the
    message content with zero subprocess involvement."""
    from lazy_harness.knowledge.compound_loop import invoke_llm
    from lazy_harness.llm import claude as claude_mod
    from lazy_harness.llm import openai_compat as openai_mod
    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend
    from lazy_harness.llm.registry import get_backend

    def _no_subprocess(*a: object, **kw: object) -> object:
        raise AssertionError("subprocess.run must not be called for the ollama backend")

    monkeypatch.setattr(claude_mod.subprocess, "run", _no_subprocess)

    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "graded locally"}}]}

    def fake_post(url, **kwargs):  # noqa: ANN001, ANN003
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(openai_mod.httpx, "post", fake_post)

    backend = get_backend(_cfg("ollama"))
    assert isinstance(backend, OpenAICompatibleBackend)

    result = invoke_llm("grade this session", backend, "llama3.2:3b", 30)

    assert result == "graded locally"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
