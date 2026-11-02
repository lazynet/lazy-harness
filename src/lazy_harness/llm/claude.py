"""ClaudeBackend — headless `claude -p` inference (ADR-033).

The subprocess call started as the historical `invoke_claude` from
knowledge/compound_loop.py: prompt on stdin, same timeout handling, failures
mapped to LLMBackendError instead of None. The argv now runs `claude -p`
isolated from the profile it inherits, so an evaluation fires no hook and
leaves no transcript (`specs/designs/claude-code-evidence.md`, 2026-11-01).

With no transcript, the JSON result envelope is the only record of what a
call spent, so the backend asks for it and reports the usage it carries.
"""

from __future__ import annotations

import json
import subprocess

from lazy_harness.llm.base import Completion, LLMBackendError, LLMTimeoutError, ModelUsage


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _model_usage(data: dict) -> tuple[ModelUsage, ...]:
    """Per model from `modelUsage`: one call can bill more than one model."""
    by_model = data.get("modelUsage")
    if not isinstance(by_model, dict):
        return ()
    usage: list[ModelUsage] = []
    for model, row in by_model.items():
        if not isinstance(model, str) or not isinstance(row, dict):
            continue
        cost = row.get("costUSD")
        usage.append(
            ModelUsage(
                model=model,
                input_tokens=_int(row.get("inputTokens")),
                output_tokens=_int(row.get("outputTokens")),
                cache_read_tokens=_int(row.get("cacheReadInputTokens")),
                cache_creation_tokens=_int(row.get("cacheCreationEphemeral5mInputTokens")),
                cache_creation_1h_tokens=_int(row.get("cacheCreationEphemeral1hInputTokens")),
                cost_usd=float(cost)
                if isinstance(cost, (int, float)) and not isinstance(cost, bool)
                else None,
            )
        )
    return tuple(usage)


def _parse(stdout: str) -> Completion:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("type") != "result":
        return Completion(text=stdout.strip())
    result = data.get("result")
    text = result.strip() if isinstance(result, str) else ""
    if data.get("is_error") is True:
        raise LLMBackendError(text or f"claude reported {data.get('subtype') or 'an error'}")
    usage = data.get("usage")
    tier = usage.get("service_tier") if isinstance(usage, dict) else None
    session_id = data.get("session_id")
    return Completion(
        text=text,
        session_id=session_id if isinstance(session_id, str) and session_id else None,
        service_tier=tier if isinstance(tier, str) else None,
        usage=_model_usage(data),
    )


class ClaudeBackend:
    @property
    def name(self) -> str:
        return "claude"

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        return self.complete_with_usage(prompt, model, timeout, schema=schema).text

    def complete_with_usage(
        self, prompt: str, model: str, timeout: int, *, schema: dict | None = None
    ) -> Completion:
        """`schema` is accepted and ignored: `claude -p` has no equivalent flag.

        Growing the argv here would pass an unknown option to the binary. The
        caller keeps `parse_response` for this backend.
        """
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model",
                    model,
                    "--output-format",
                    "json",
                    # Empty list loads no user settings, so no settings or
                    # plugin hook fires; OAuth still works, unlike --bare.
                    "--setting-sources",
                    "",
                    # No transcript under projects/ for ingest, export or the
                    # compound loop to read back as a user session.
                    "--no-session-persistence",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMTimeoutError(str(e)) from e
        except (FileNotFoundError, OSError) as e:
            raise LLMBackendError(str(e)) from e
        if result.returncode != 0:
            raise LLMBackendError(result.stderr.strip() or f"claude exited {result.returncode}")
        return _parse(result.stdout)
