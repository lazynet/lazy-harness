"""Role → backend resolution (ADR-039).

`registry.py` answers "how do I call this provider". This module answers "who
should answer this call". Keeping that second question in one importable place
is what lets the capability registry and `run_inference` be tested for
agreement instead of drifting into two answers.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from lazy_harness.core.config import Config

#: The role the deprecated `[compound_loop].backend` form maps onto.
DEPRECATED_ROLE = "distill"

#: Once-per-process latch. A deprecation notice repeated on every session the
#: worker processes is noise the operator learns to skip.
_warned = False


class RoleNotFoundError(Exception):
    """Raised when a role, or the backend it names, is not defined."""


@dataclass(frozen=True)
class ResolvedRole:
    role: str
    backend_name: str
    type: str
    model: str
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""


def resolve_role(cfg: Config, role: str) -> ResolvedRole:
    """Resolve `role` to the backend that should serve it.

    The `[llm]` table wins. Only when it does not define the role does the
    deprecated `[compound_loop]` form apply, and only for `distill` — the
    synthetic name that form maps onto.
    """
    backend_name = cfg.llm.roles.get(role)
    if backend_name is not None:
        backend = cfg.llm.backends.get(backend_name)
        if backend is None:
            known = ", ".join(sorted(cfg.llm.backends)) or "none"
            raise RoleNotFoundError(
                f"role {role!r} names backend {backend_name!r}, which is not defined "
                f"in [llm.backends] (defined: {known})"
            )
        return ResolvedRole(
            role=role,
            backend_name=backend_name,
            type=backend.type,
            model=backend.model,
            base_url=backend.base_url,
            api_key=backend.api_key,
            api_key_env=backend.api_key_env,
        )

    if role == DEPRECATED_ROLE:
        _warn_deprecated_once()
        options = cfg.compound_loop.backend_options
        return ResolvedRole(
            role=role,
            backend_name="compound_loop",
            type=cfg.compound_loop.backend,
            model=cfg.compound_loop.model,
            base_url=options.get("base_url", ""),
            api_key=options.get("api_key", ""),
        )

    known = ", ".join(sorted(cfg.llm.roles)) or "none"
    raise RoleNotFoundError(f"role {role!r} is not defined in [llm.roles] (defined: {known})")


def _warn_deprecated_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    warnings.warn(
        "[compound_loop].backend and .model are deprecated; declare the backend "
        "under [llm.backends] and point [llm.roles].distill at it",
        DeprecationWarning,
        stacklevel=3,
    )
