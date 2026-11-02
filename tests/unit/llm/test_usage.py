"""Inference usage reaches metrics.db through the sinks (ADR-039 Evolution)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lazy_harness.core.config import (
    Config,
    LLMBackendConfig,
    LLMConfig,
    ProfileEntry,
)
from lazy_harness.llm.base import Completion, ModelUsage

_MODEL = "claude-haiku-4-5-20251001"


@pytest.fixture(autouse=True)
def _isolated_metrics_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`resolve_db_path` honours `LH_DATA_DIR`, which no suite-wide fixture
    clears: without this a developer who exports it gets rows in the real DB."""
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "config"))


_DAY = "2026-11-01"


def _usage(**overrides: int) -> ModelUsage:
    fields = {
        "input_tokens": 9,
        "output_tokens": 66,
        "cache_read_tokens": 14595,
        "cache_creation_tokens": 300,
        "cache_creation_1h_tokens": 8386,
    }
    fields.update(overrides)
    return ModelUsage(model=_MODEL, cost_usd=0.0185705, **fields)


def _completion(session_id: str | None = "sess-1") -> Completion:
    return Completion(text="OK", session_id=session_id, service_tier="standard", usage=(_usage(),))


def _events(completion: Completion, *, billing_model: str = "flat_rate"):
    from lazy_harness.llm.usage import usage_events
    from lazy_harness.monitoring.pricing import load_pricing

    return usage_events(
        completion,
        role="distill",
        backend="claude",
        profile="lazy",
        billing_model=billing_model,
        pricing=load_pricing(),
        user_id="u",
        tenant_id="t",
        host="h",
        day=_DAY,
    )


def test_a_call_is_one_event_per_model_attributed_to_its_role() -> None:
    from lazy_harness.monitoring.event_id import derive_event_id
    from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION

    (event,) = _events(_completion())

    assert event.session == "sess-1"
    assert event.model == _MODEL
    assert event.workload == "inference:distill"
    assert event.agent == "claude"
    assert event.profile == "lazy"
    assert event.event_id == derive_event_id(profile="lazy", session="sess-1", model=_MODEL)
    assert event.schema_version == METRIC_EVENT_SCHEMA_VERSION
    assert (event.input_tokens, event.output_tokens, event.cache_read) == (9, 66, 14595)
    assert event.cache_create == 300 + 8386


def test_a_flat_rate_call_bills_nothing_and_keeps_its_api_equivalent() -> None:
    (event,) = _events(_completion(), billing_model="flat_rate")

    assert event.billing_model == "flat_rate"
    assert event.cost == 0.0
    assert event.cost_source == "subscription"
    assert event.billed_cost is None
    assert event.billed_cost_source == "subscription"
    assert event.api_equivalent_status == "priced"
    assert event.api_equivalent_cost is not None and event.api_equivalent_cost > 0


def test_a_per_token_call_is_billed_from_the_pricing_table() -> None:
    (event,) = _events(_completion(), billing_model="per_token")

    assert event.cost_source == "pricing"
    assert event.cost > 0
    assert event.billed_cost == event.cost
    assert event.billed_cost_source == "pricing"


def test_a_call_with_no_provider_session_id_still_gets_its_own_row() -> None:
    (first,) = _events(_completion(session_id=None))
    (second,) = _events(_completion(session_id=None))

    assert first.session and second.session
    assert first.session != second.session


def test_usage_events_price_a_call_exactly_as_the_ingest_prices_its_transcript(
    tmp_path: Path,
) -> None:
    """Two paths answer "what did this response cost": the ingest, for
    transcripts, and this module, for calls that leave none. The same tokens
    must get the same row from both."""
    from lazy_harness.core.profiles import ProfileInfo
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    usage = _usage()
    config_dir = tmp_path / "lazy"
    session_dir = config_dir / "projects" / "-w-demo"
    session_dir.mkdir(parents=True)
    line = {
        "type": "assistant",
        "timestamp": f"{_DAY}T10:00:00",
        "message": {
            "id": "msg_1",
            "model": _MODEL,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": usage.cache_read_tokens,
                "cache_creation_input_tokens": usage.cache_creation_tokens
                + usage.cache_creation_1h_tokens,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": usage.cache_creation_tokens,
                    "ephemeral_1h_input_tokens": usage.cache_creation_1h_tokens,
                },
            },
        },
    }
    (session_dir / "sess-1.jsonl").write_text(json.dumps(line) + "\n")
    prof = ProfileInfo(name="lazy", config_dir=config_dir, roots=[], is_default=True, exists=True)

    for billing_model in ("flat_rate", "per_token"):
        db = MetricsDB(tmp_path / f"{billing_model}.db")
        captured: list = []

        class _Capture:
            def write(self, event):  # noqa: ANN001, ANN202
                captured.append(event)

                class _Ok:
                    success = True

                return _Ok()

        ingest_profile(prof, db, load_pricing(), sinks=[_Capture()], billing_model=billing_model)
        db.close()
        (ingested,) = captured
        (recorded,) = _events(_completion(), billing_model=billing_model)

        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read",
            "cache_create",
            "cost",
            "cost_source",
            "billed_cost",
            "billed_cost_source",
            "api_equivalent_cost",
            "api_equivalent_status",
            "api_price_basis",
        ):
            assert getattr(recorded, name) == getattr(ingested, name), (billing_model, name)


# --- run_inference writes the row ----------------------------------------


class _UsageBackend:
    def __init__(self, completion: Completion) -> None:
        self._completion = completion

    @property
    def name(self) -> str:
        return "claude"

    def default_model(self) -> str:
        return _MODEL

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        return self._completion.text

    def complete_with_usage(
        self, prompt: str, model: str, timeout: int, *, schema: dict | None = None
    ) -> Completion:
        return self._completion


class _TextOnlyBackend:
    """An `LLMBackend` with no `complete_with_usage` — every openai_compat one."""

    @property
    def name(self) -> str:
        return "ollama"

    def default_model(self) -> str:
        return "m"

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        return "OK"


def _cfg(*, enabled: bool = True) -> Config:
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={"c": LLMBackendConfig(type="claude", model=_MODEL)},
        roles={"distill": "c"},
    )
    cfg.monitoring.enabled = enabled
    cfg.profiles.items = {"lazy": ProfileEntry(billing_model="flat_rate")}
    return cfg


def _run(monkeypatch: pytest.MonkeyPatch, backend: object, cfg: Config, **kwargs):  # noqa: ANN003
    from lazy_harness.llm import invoke as mod

    monkeypatch.setattr(mod, "build_backend", lambda **kw: backend)
    return mod.run_inference("p", role="distill", cfg=cfg, timeout=5, **kwargs)


def _rows() -> list[sqlite3.Row]:
    from lazy_harness.monitoring.db import resolve_db_path

    path = resolve_db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM session_stats").fetchall()
    finally:
        conn.close()


def test_run_inference_records_the_call_in_metrics_db(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run(monkeypatch, _UsageBackend(_completion()), _cfg())

    assert result.success and result.output == "OK"
    (row,) = _rows()
    assert row["session"] == "sess-1"
    assert row["workload"] == "inference:distill"
    assert row["model"] == _MODEL


def test_a_backend_that_reports_no_usage_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run(monkeypatch, _TextOnlyBackend(), _cfg())

    assert result.success and result.output == "OK"
    assert _rows() == []


def test_monitoring_disabled_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run(monkeypatch, _UsageBackend(_completion()), _cfg(enabled=False))

    assert result.success
    assert _rows() == []


def test_a_schema_violation_is_still_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tokens were billed whether or not the answer was usable."""
    result = _run(
        monkeypatch,
        _UsageBackend(_completion()),
        _cfg(),
        schema={"type": "object", "required": ["x"]},
    )

    assert not result.success
    assert result.error is not None and result.error.kind == "schema-violation"
    assert len(_rows()) == 1


def test_a_failing_metrics_layer_never_changes_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring import sink_setup

    def boom(*a, **kw):  # noqa: ANN002, ANN003
        raise RuntimeError("sink exploded")

    monkeypatch.setattr(sink_setup, "build_sinks", boom)

    result = _run(monkeypatch, _UsageBackend(_completion()), _cfg())

    assert result.success and result.output == "OK" and result.error is None
