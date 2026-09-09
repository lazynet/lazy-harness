"""run_inference — the single inference resolution seam (ADR-039).

Every framework-internal model call and every `lh exec --role` invocation comes
through this function. It resolves the role, executes, times the call, and maps
every failure onto a named kind. **It never raises**: a caller holding an
`InferenceResult` has a complete account of what happened.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from lazy_harness.core.config import Config
from lazy_harness.llm.base import LLMBackendError, LLMTimeoutError
from lazy_harness.llm.registry import build_backend
from lazy_harness.llm.roles import RoleNotFoundError, resolve_role

#: Exhaustive for `mode: "inference"`. ADR-038's `no-envelope` and
#: `agent-error` belong to the agent path and never appear here, so a consumer
#: may implement these as a closed enum.
INFERENCE_KINDS: tuple[str, ...] = (
    "backend-unreachable",
    "timeout",
    "schema-violation",
    "empty",
    "backend-error",
)


@dataclass(frozen=True)
class InferenceError:
    kind: str
    message: str


@dataclass(frozen=True)
class InferenceResult:
    #: Always a string, never None — `""` when there is nothing to return,
    #: including on every failure path.
    output: str
    success: bool
    model: str
    backend: str
    duration_ms: int
    error: InferenceError | None


def _validate(payload: object, schema: dict) -> str:
    """Return `""` when valid, else a human reason.

    Not a JSON Schema implementation. It checks the three properties the
    backend was *asked* to enforce, so a backend that ignored the request —
    `claude -p` has no such flag, and older servers silently drop it — is
    caught rather than trusted.
    """
    if schema.get("type") == "object" and not isinstance(payload, dict):
        return f"expected an object, got {type(payload).__name__}"
    if not isinstance(payload, dict):
        return ""
    for key in schema.get("required", []):
        if key not in payload:
            return f"missing required key {key!r}"
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, spec in properties.items():
            if not isinstance(spec, dict):
                continue
            allowed = spec.get("enum")
            if allowed and key in payload and payload[key] not in allowed:
                return f"{key}={payload[key]!r} is outside {allowed!r}"
    return ""


def _resolve_api_key(resolved_api_key: str, api_key_env: str) -> str:
    """Read the key at call time so the value never reaches disk.

    A scheduler job inherits no interactive shell, so `api_key_env` must be
    set in the job definition itself — launchd `EnvironmentVariables`, systemd
    `EnvironmentFile` — not in shell init, which no scheduler reads.
    """
    if api_key_env:
        return os.environ.get(api_key_env, "")
    return resolved_api_key


def run_inference(
    prompt: str,
    *,
    role: str,
    cfg: Config,
    timeout: int,
    schema: dict | None = None,
) -> InferenceResult:
    """Run one single-turn completion through the backend `role` names.

    There is deliberately **no fallback to another backend**. A silent
    fall-through from a local backend to a billed one is how a cost
    optimisation becomes a cost surprise, and it hides a broken local backend
    behind an invoice. Callers that want one retry with a different role.
    """
    started = time.perf_counter()

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def _fail(kind: str, message: str, *, backend: str = "", model: str = "") -> InferenceResult:
        return InferenceResult(
            output="",
            success=False,
            model=model,
            backend=backend,
            duration_ms=_elapsed_ms(),
            error=InferenceError(kind=kind, message=message),
        )

    try:
        target = resolve_role(cfg, role)
    except RoleNotFoundError as e:
        return _fail("backend-unreachable", str(e))

    try:
        backend = build_backend(
            type=target.type,
            base_url=target.base_url,
            api_key=_resolve_api_key(target.api_key, target.api_key_env),
        )
    except Exception as e:
        return _fail("backend-unreachable", str(e), backend=target.type)

    model = target.model or backend.default_model()

    try:
        output = backend.complete(prompt, model, timeout, schema=schema)
    except LLMTimeoutError as e:
        return _fail("timeout", str(e) or "timed out", backend=target.type, model=model)
    except LLMBackendError as e:
        return _fail("backend-unreachable", str(e), backend=target.type, model=model)
    except Exception as e:  # a backend that raised something undeclared
        return _fail("backend-error", str(e), backend=target.type, model=model)

    if not output:
        return _fail("empty", "backend returned no output", backend=target.type, model=model)

    if schema is not None:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as e:
            return _fail(
                "schema-violation",
                f"response is not JSON: {e}",
                backend=target.type,
                model=model,
            )
        reason = _validate(payload, schema)
        if reason:
            return _fail("schema-violation", reason, backend=target.type, model=model)

    return InferenceResult(
        output=output,
        success=True,
        model=model,
        backend=target.type,
        duration_ms=_elapsed_ms(),
        error=None,
    )
