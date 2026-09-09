"""Role → backend resolution and the ADR-033 deprecation bridge (ADR-039)."""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, LLMBackendConfig, LLMConfig


def _cfg_with_roles(backends: dict[str, LLMBackendConfig], roles: dict[str, str]) -> Config:
    cfg = Config()
    cfg.llm = LLMConfig(backends=backends, roles=roles)
    return cfg


def test_resolves_role_to_its_backend() -> None:
    from lazy_harness.llm.roles import resolve_role

    cfg = _cfg_with_roles(
        {"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        {"classify": "local"},
    )
    resolved = resolve_role(cfg, "classify")
    assert resolved.type == "ollama"
    assert resolved.model == "qwen2.5-coder:7b"
    assert resolved.backend_name == "local"


def test_carries_base_url_and_api_key_env_through() -> None:
    from lazy_harness.llm.roles import resolve_role

    cfg = _cfg_with_roles(
        {
            "r": LLMBackendConfig(
                type="openai-compatible",
                base_url="https://example.invalid/v1",
                api_key_env="SOME_VAR",
            )
        },
        {"classify": "r"},
    )
    resolved = resolve_role(cfg, "classify")
    assert resolved.base_url == "https://example.invalid/v1"
    assert resolved.api_key_env == "SOME_VAR"


def test_role_naming_undefined_backend_is_an_error() -> None:
    from lazy_harness.llm.roles import RoleNotFoundError, resolve_role

    cfg = _cfg_with_roles({}, {"classify": "ghost"})
    with pytest.raises(RoleNotFoundError, match="ghost"):
        resolve_role(cfg, "classify")


def test_undefined_role_names_the_roles_that_exist() -> None:
    from lazy_harness.llm.roles import RoleNotFoundError, resolve_role

    cfg = _cfg_with_roles({"local": LLMBackendConfig()}, {"classify": "local"})
    with pytest.raises(RoleNotFoundError, match="classify"):
        resolve_role(cfg, "nope")


def test_compound_loop_backend_maps_to_synthetic_distill_role() -> None:
    """The ADR-033 form keeps working with no [llm] table at all."""
    from lazy_harness.llm.roles import resolve_role

    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    cfg.compound_loop.model = "llama3.2:3b"
    resolved = resolve_role(cfg, "distill")
    assert resolved.type == "ollama"
    assert resolved.model == "llama3.2:3b"


def test_deprecated_backend_options_carry_base_url() -> None:
    from lazy_harness.llm.roles import resolve_role

    cfg = Config()
    cfg.compound_loop.backend = "openai-compatible"
    cfg.compound_loop.backend_options = {"base_url": "http://gpu-box:11434"}
    assert resolve_role(cfg, "distill").base_url == "http://gpu-box:11434"


def test_llm_table_wins_over_deprecated_compound_loop_fields() -> None:
    from lazy_harness.llm.roles import resolve_role

    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    cfg.llm = LLMConfig(
        backends={"h": LLMBackendConfig(type="claude", model="claude-haiku-4-5-20251001")},
        roles={"distill": "h"},
    )
    assert resolve_role(cfg, "distill").type == "claude"


def test_deprecated_form_warns_once_per_process() -> None:
    import warnings

    from lazy_harness.llm import roles as roles_mod

    roles_mod._warned = False
    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        roles_mod.resolve_role(cfg, "distill")
        roles_mod.resolve_role(cfg, "distill")
    hits = [w for w in caught if "compound_loop" in str(w.message)]
    assert len(hits) == 1


def test_llm_table_form_does_not_warn() -> None:
    import warnings

    from lazy_harness.llm import roles as roles_mod

    roles_mod._warned = False
    cfg = _cfg_with_roles({"h": LLMBackendConfig(type="claude")}, {"distill": "h"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        roles_mod.resolve_role(cfg, "distill")
    assert [w for w in caught if "compound_loop" in str(w.message)] == []
