"""ClaudeBackend — headless `claude -p` inference (ADR-033).

The subprocess call is the historical `invoke_claude` from
knowledge/compound_loop.py, extracted verbatim: same argv, prompt on stdin,
same timeout handling. Failures map to LLMBackendError instead of None.
"""

from __future__ import annotations

import subprocess

from lazy_harness.llm.base import LLMBackendError


class ClaudeBackend:
    @property
    def name(self) -> str:
        return "claude"

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    def complete(self, prompt: str, model: str, timeout: int) -> str:
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model, "--output-format", "text"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            raise LLMBackendError(str(e)) from e
        return result.stdout.strip()
