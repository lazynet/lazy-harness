"""lh exec — run the configured agent headlessly and emit a normalised result.

`lh run` execs the agent and gets out of the way. `lh exec` cannot: it has to
survive the child in order to normalise its output, so it also takes on the
child's lifetime — the timeout and the process-group teardown live here.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import NoReturn

import click

from lazy_harness import __version__
from lazy_harness.agents.base import (
    HEADLESS_TIERS,
    HeadlessAgent,
    HeadlessResult,
    SessionPinningAgent,
)
from lazy_harness.agents.launch import LaunchError, LaunchPlan, resolve_launch
from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, process_exec_path

SCHEMA = "lh.exec/v1"

EXIT_HARNESS_ERROR = 70
EXIT_TIMEOUT = 124

_GRACE_SECONDS = 5.0


def _emit(envelope: dict) -> None:
    """Write the envelope to stdout. Nothing else may ever go there."""
    click.echo(json.dumps(envelope))


def _base_envelope() -> dict:
    return {
        "schema": SCHEMA,
        "dry_run": False,
        "success": False,
        "exit_code": EXIT_HARNESS_ERROR,
        "output": "",
        "cost_usd": None,
        "duration_ms": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "cache_creation_tokens": None,
        "cache_read_tokens": None,
        "num_turns": None,
        "error": None,
        "harness": None,
        "raw": None,
    }


def _harness_block(plan: LaunchPlan, argv: list[str]) -> dict:
    return {
        "profile": plan.profile,
        "profile_source": plan.profile_source,
        "agent": plan.adapter.name,
        "binary": str(plan.binary),
        "config_dir": str(plan.config_dir),
        "lh_version": __version__,
        "argv": argv,
    }


def _fail(kind: str, message: str, harness: dict | None = None) -> NoReturn:
    envelope = _base_envelope()
    envelope["error"] = {"kind": kind, "message": message}
    envelope["harness"] = harness
    _emit(envelope)
    raise SystemExit(EXIT_HARNESS_ERROR)


def _record_attribution(session_id: str, workload: str, *, replaces: str | None = None) -> None:
    """Attach `workload` to `session_id` in the metrics store.

    Called before the agent is spawned so a run killed by the timeout — the
    most expensive outcome this command has — is still attributed. The ingest
    is the only subsystem that accounts for such a run; this envelope reports
    `cost_usd: null` for it.

    Fail-soft by construction: attribution is bookkeeping about a run and must
    never be the reason the run fails.
    """
    try:
        from lazy_harness.core.identity import resolve_host
        from lazy_harness.monitoring.db import MetricsDB, resolve_db_path

        db = MetricsDB(resolve_db_path())
        try:
            db.set_attribution(session=session_id, workload=workload, host=resolve_host())
            if replaces is not None and replaces != session_id:
                db.delete_attribution(replaces)
        finally:
            db.close()
    except Exception:
        pass


def _terminate_group(proc: subprocess.Popen) -> None:
    """Kill the child *and* whatever it spawned.

    Killing only the direct child leaves grandchildren — MCP servers, model
    calls already in flight — running and billable.
    """
    pgid: int | None = None
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = None

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if pgid is None:
                proc.send_signal(sig)
            else:
                os.killpg(pgid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue


@click.command("exec")
@click.option("--profile", "profile_override", default=None, help="Force a specific profile")
@click.option(
    "--tier",
    type=click.Choice(HEADLESS_TIERS),
    default=None,
    help="Capability tier; the adapter maps it to a provider model",
)
@click.option("--model", default=None, help="Explicit provider model id (wins over --tier)")
@click.option("--allow-tools", default=None, help="Comma-separated tools to grant")
@click.option("--no-tools", is_flag=True, help="Deny every tool the agent can be told to deny")
@click.option(
    "--timeout",
    type=float,
    default=600.0,
    show_default=True,
    help="Seconds before the agent's process group is killed. 0 disables.",
)
@click.option(
    "--workload",
    default="",
    envvar="LH_WORKLOAD",
    help="Attribution label for this run, recorded against its session id.",
)
@click.option("--dry-run", is_flag=True, help="Emit the plan without spawning the agent")
@click.argument("agent_args", nargs=-1, type=click.UNPROCESSED)
def exec_cmd(
    profile_override: str | None,
    tier: str | None,
    model: str | None,
    allow_tools: str | None,
    no_tools: bool,
    timeout: float,
    workload: str,
    dry_run: bool,
    agent_args: tuple[str, ...],
) -> None:
    """Run the agent headlessly, reading the prompt from stdin.

    Writes one JSON envelope to stdout; the agent's stderr passes through
    untouched. Args after `--` are forwarded to the agent verbatim.
    """
    if tier and model:
        raise click.UsageError("--tier and --model are mutually exclusive")
    if allow_tools is not None and no_tools:
        raise click.UsageError("--allow-tools and --no-tools are mutually exclusive")
    if allow_tools is not None and not allow_tools.strip():
        raise click.UsageError(
            "--allow-tools needs at least one tool; use --no-tools to deny them all"
        )

    allowed_tools: list[str] | None = None
    if no_tools:
        allowed_tools = []
    elif allow_tools is not None:
        allowed_tools = [t.strip() for t in allow_tools.split(",") if t.strip()]

    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        _fail("config", str(e))

    try:
        plan = resolve_launch(cfg, Path.cwd(), profile_override, require_headless=True)
    except LaunchError as e:
        _fail(e.kind, str(e))

    adapter = plan.adapter
    assert isinstance(adapter, HeadlessAgent)  # resolve_launch already refused otherwise

    try:
        resolved_model = adapter.resolve_model(tier=tier, explicit=model)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    # A fresh id every invocation, never remembered: the agent refuses one
    # already in use with exit 1 and an empty stdout.
    session_id = str(uuid.uuid4())
    pin = adapter.session_argv(session_id) if isinstance(adapter, SessionPinningAgent) else []
    tail = [
        *adapter.headless_argv(model=resolved_model, allowed_tools=allowed_tools),
        *pin,
        *agent_args,
    ]
    harness = _harness_block(plan, [str(plan.binary), *tail])

    if dry_run:
        envelope = _base_envelope()
        envelope.update({"dry_run": True, "success": True, "exit_code": 0, "harness": harness})
        _emit(envelope)
        return

    prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not prompt.strip():
        _fail("empty-prompt", "No prompt on stdin.", harness)

    # Before the spawn, so the attribution outlives a kill. An empty workload
    # writes nothing: the table must not grow a row on every unlabelled run.
    if workload:
        _record_attribution(session_id, workload)

    process_name = adapter.process_name()
    executable = process_exec_path(plan.binary, process_name) if process_name else plan.binary
    argv = [process_name or str(plan.binary), *tail]

    try:
        proc = subprocess.Popen(
            argv,
            executable=str(executable),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            env=plan.env,
            start_new_session=os.name == "posix",
        )
    except OSError as e:
        _fail("spawn-failed", str(e), harness)

    try:
        stdout, _ = proc.communicate(prompt, timeout=timeout or None)
    except subprocess.TimeoutExpired:
        _terminate_group(proc)
        try:
            proc.communicate(timeout=_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        envelope = _base_envelope()
        envelope["exit_code"] = EXIT_TIMEOUT
        envelope["error"] = {"kind": "timeout", "message": f"Agent exceeded {timeout}s."}
        envelope["harness"] = harness
        _emit(envelope)
        raise SystemExit(EXIT_TIMEOUT) from None

    result: HeadlessResult = adapter.parse_headless_result(stdout, proc.returncode)

    # An exit code is not proof the pin took effect. If the agent named a
    # different conversation, the attribution belongs to that one.
    if workload and result.session_id and result.session_id != session_id:
        _record_attribution(result.session_id, workload, replaces=session_id)

    envelope = _base_envelope()
    envelope.update(
        {
            "success": result.success,
            "exit_code": result.exit_code,
            "output": result.output,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "cache_creation_tokens": result.cache_creation_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "num_turns": result.num_turns,
            "harness": harness,
            "raw": result.raw,
        }
    )
    _emit(envelope)
    raise SystemExit(result.exit_code)
