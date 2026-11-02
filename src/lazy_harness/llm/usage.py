"""Inference spend into metrics.db (ADR-039 Evolution, 2026-11-01).

A backend call isolated from the profile leaves no transcript, so the ingest
never sees it. The provider's own usage report is the only record, and this
module turns it into the same `MetricEvent` the ingest would have built from
a transcript of that one response, written through the same sinks.

The row is keyed by the provider's id for the call and labelled
`inference:<role>` in `workload`, so it is never mistaken for a user session.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from lazy_harness.core.config import Config
from lazy_harness.llm.base import Completion
from lazy_harness.monitoring.event_id import derive_event_id
from lazy_harness.monitoring.pricing import (
    anthropic_context_class,
    cost_for_billing_model,
    price_api_response,
)
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent

WORKLOAD_PREFIX = "inference:"


def usage_events(
    completion: Completion,
    *,
    role: str,
    backend: str,
    profile: str,
    billing_model: str,
    pricing: dict[str, dict[str, float]],
    user_id: str,
    tenant_id: str,
    host: str,
    day: str,
) -> list[MetricEvent]:
    """One event per model the call billed, priced as `ingest_profile` prices
    one transcript response (`test_usage_events_price_a_call_exactly_as_...`)."""
    session = completion.session_id or uuid.uuid4().hex
    events: list[MetricEvent] = []
    for usage in completion.usage:
        tokens = {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_read": usage.cache_read_tokens,
            "cache_create": usage.cache_creation_tokens,
            "cache_create_1h": usage.cache_creation_1h_tokens,
        }
        cost, cost_source = cost_for_billing_model(
            usage.model,
            tokens,
            pricing,
            billing_model=billing_model,
            on=day,
            context_class=anthropic_context_class(usage.model, tokens),
        )
        cost = round(cost, 6)
        if billing_model == "flat_rate":
            billed_cost, billed_cost_source = None, "subscription"
        elif cost_source == "pricing":
            billed_cost, billed_cost_source = cost, "pricing"
        else:
            billed_cost, billed_cost_source = None, "unknown"
        equivalent = price_api_response(
            usage.model,
            tokens,
            service_tier=completion.service_tier or "standard",
            context_class=None,
            on=day,
        )
        priced = equivalent.status == "priced"
        events.append(
            MetricEvent(
                event_id=derive_event_id(profile=profile, session=session, model=usage.model),
                schema_version=METRIC_EVENT_SCHEMA_VERSION,
                user_id=user_id,
                tenant_id=tenant_id,
                profile=profile,
                session=session,
                model=usage.model,
                project="",
                date=day,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read=usage.cache_read_tokens,
                cache_create=usage.cache_creation_tokens + usage.cache_creation_1h_tokens,
                cost=cost,
                host=host,
                workload=f"{WORKLOAD_PREFIX}{role}",
                # The inference backend, not an agent adapter: no agent ran.
                agent=backend,
                billing_model=billing_model,
                cost_source=cost_source,
                billed_cost=billed_cost,
                billed_cost_source=billed_cost_source,
                api_equivalent_cost=(equivalent.amount or 0.0) if priced else None,
                api_equivalent_status=equivalent.status,
                api_price_basis=(
                    asdict(equivalent.basis) if priced and equivalent.basis is not None else None
                ),
            )
        )
    return events


def record_usage(completion: Completion, *, role: str, backend: str, cfg: Config) -> None:
    """Write `completion`'s usage through every active sink.

    Fail-soft by construction, like `lh exec`'s attribution: accounting about
    a call must never be the reason the call fails.
    """
    if not cfg.monitoring.enabled or not completion.usage:
        return
    try:
        from datetime import date

        from lazy_harness.core.identity import resolve_host, resolve_identity
        from lazy_harness.hooks.builtins._shared import profile_name
        from lazy_harness.monitoring import sink_setup
        from lazy_harness.monitoring.db import MetricsDB, resolve_db_path
        from lazy_harness.monitoring.pricing import load_pricing

        profile = profile_name()
        entry = cfg.profiles.items.get(profile)
        events = usage_events(
            completion,
            role=role,
            backend=backend,
            profile=profile,
            billing_model=entry.billing_model if entry is not None else "per_token",
            pricing=load_pricing(cfg.monitoring.pricing or None),
            user_id=resolve_identity(explicit=cfg.metrics.user_id or None).user_id,
            tenant_id=cfg.metrics.tenant_id,
            host=resolve_host(),
            day=date.today().isoformat(),
        )
        db = MetricsDB(resolve_db_path())
        try:
            for sink in sink_setup.build_sinks(cfg.metrics, db=db):
                for event in events:
                    sink.write(event)
        finally:
            db.close()
    except Exception:
        pass
