"""Hook execution engine — run hooks and collect results."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass

from lazy_harness.hooks.loader import _BUILTIN_HOOKS, HookInfo
from lazy_harness.hooks.runner import resolve_profile, run_hook


@dataclass
class HookResult:
    hook_name: str
    event: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


def execute_hook(
    hook: HookInfo,
    event: str,
    payload: dict,
    timeout: int = 30,
    profile: str | None = None,
) -> HookResult:
    """Run one hook and report its three channels.

    A migrated builtin goes through the runner in this process; everything else
    is still the hook *file* in a subprocess — an unmigrated builtin, whose
    `main()` reads stdin and exits by itself, and a user hook, which the
    registry never heard of and which has no `main(event)` to call at all.
    """
    spec = _BUILTIN_HOOKS.get(hook.name) if hook.is_builtin else None
    if spec is not None and spec.migrated:
        start = time.monotonic()
        output = run_hook(
            hook.name,
            profile=resolve_profile(profile),
            stdin_text=json.dumps(payload),
        )
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=output.exit_code,
            stdout=output.stdout or "",
            stderr=output.stderr,
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=False,
        )

    start = time.monotonic()
    cmd = [sys.executable, str(hook.path)]
    input_data = json.dumps(payload)

    try:
        result = subprocess.run(
            cmd, input=input_data, capture_output=True, text=True, timeout=timeout
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=-1,
            stdout="",
            stderr=f"Hook timed out after {timeout}s",
            duration_ms=duration_ms,
            timed_out=True,
        )
    except OSError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration_ms,
            timed_out=False,
        )


def run_hooks_for_event(
    hooks: list[HookInfo],
    event: str,
    payload: dict,
    timeout: int = 30,
    profile: str | None = None,
) -> list[HookResult]:
    results: list[HookResult] = []
    for hook in hooks:
        result = execute_hook(hook, event, payload, timeout, profile)
        results.append(result)
    return results
