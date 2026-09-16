"""Hook execution engine — run hooks and collect results."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass

from lazy_harness.hooks.loader import HookInfo
from lazy_harness.hooks.runner import resolve_profile

#: How to reach the installed CLI from a known interpreter. `sys.executable` is
#: the only thing that guarantees the interpreter with the package installed,
#: and a bare `lh` would resolve against an ambient PATH the caller does not
#: control. Shared with the golden harness so the bytes frozen there are the
#: bytes this engine reads.
CLI_BOOTSTRAP = "from lazy_harness.cli.main import cli; cli()"


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

    A builtin is reached through the command the agent's settings file invokes
    — `lh hook <name> --profile <profile>` — so `lh hooks run` debugs the
    deployed path rather than a second execution mechanism. A user hook is
    still the hook *file*: the registry never heard of it, so there is no
    `main(event)` to call and no profile to hand one.

    The branch reads `is_builtin` and nothing else. It used to consult
    `BuiltinHookSpec.migrated` as well, which was the transitional answer to
    "does this module's `main()` take an argument"; with every builtin on the
    contract the question has one answer and the flag is gone.

    Both go through one `subprocess.run`, which is what makes `timeout` mean
    something on either. Calling the runner in this process could not: Python
    cannot interrupt a synchronous call, so the branch ignored `timeout` and
    reported `timed_out=False` unconditionally.

    The argument vector is a list, so the profile needs no quoting here — the
    quoting in `deploy.engine.hook_command` exists because *that* command is a
    string in a settings file.
    """
    if hook.is_builtin:
        cmd = [
            sys.executable,
            "-c",
            CLI_BOOTSTRAP,
            "hook",
            hook.name,
            "--profile",
            resolve_profile(profile),
        ]
    else:
        cmd = [sys.executable, str(hook.path)]

    start = time.monotonic()
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
