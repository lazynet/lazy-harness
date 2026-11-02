"""ClaudeBackend — headless `claude -p` inference (ADR-033).

The subprocess call started as the historical `invoke_claude` from
knowledge/compound_loop.py: prompt on stdin, same timeout handling, failures
mapped to LLMBackendError instead of None. The argv now runs `claude -p`
isolated from the profile it inherits, so an evaluation fires no hook and
leaves no transcript (`specs/designs/claude-code-evidence.md`, 2026-11-01).
"""

from __future__ import annotations

import subprocess

from lazy_harness.llm.base import LLMBackendError, LLMTimeoutError


class ClaudeBackend:
    @property
    def name(self) -> str:
        return "claude"

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
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
                    "text",
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
        return result.stdout.strip()
