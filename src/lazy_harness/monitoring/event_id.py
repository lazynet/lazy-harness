"""Deterministic event_id derivation for metric rows.

Uses SHA-256 of a canonical string so the same (profile, session, model)
tuple always yields the same id across machines and re-ingests. The remote
backend applies upsert-by-event_id for idempotency.
"""

from __future__ import annotations

import hashlib


def derive_event_id(*, profile: str, session: str, model: str) -> str:
    raw = f"{profile}\x1f{session}\x1f{model}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]
