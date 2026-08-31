"""Tests for `lh exec` — the headless invocation seam.

The agent binary is faked by dropping an executable where the Claude Code
adapter already looks (`~/.local/share/claude/versions/`), so these exercise
the real adapter, the real binary resolution and a real child process rather
than a mock of any of them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

ECHO_AGENT = """
    import json, os, sys
    prompt = sys.stdin.read()
    print(json.dumps({
        "is_error": False,
        "result": prompt.strip(),
        "duration_ms": 5,
        "num_turns": 1,
        "total_cost_usd": 0.5,
        "usage": {
            "input_tokens": 1,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
            "output_tokens": 4,
        },
        "argv": sys.argv[1:],
        "config_dir_seen": os.environ.get("CLAUDE_CONFIG_DIR", ""),
    }))
"""


def _write_agent(body: str) -> Path:
    """Install a fake agent binary where `ClaudeCodeAdapter` looks for one."""
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}")
    binary.chmod(0o755)
    return binary


@pytest.fixture
def harness_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A two-profile config; `work` matches a root, nothing else does."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    work_root = tmp_path / "work"
    work_root.mkdir()
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "personal"\n\n'
        f'[profiles.personal]\nconfig_dir = "{tmp_path / "cfg-personal"}"\nroots = []\n\n'
        f'[profiles.work]\nconfig_dir = "{tmp_path / "cfg-work"}"\nroots = ["{work_root}"]\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    return lh_config


def _invoke(args: list[str], prompt: str | None = "hello") -> tuple[int, dict]:
    """Run `lh exec` in-process and return (exit_code, parsed envelope)."""
    from lazy_harness.cli.exec_cmd import exec_cmd

    runner = CliRunner()
    result = runner.invoke(exec_cmd, args, input=prompt)
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        envelope = {}
    return result.exit_code, envelope


# --- envelope --------------------------------------------------------------


def test_exec_writes_a_normalised_envelope_to_stdout(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, envelope = _invoke([])

    assert code == 0
    assert envelope["success"] is True
    assert envelope["exit_code"] == 0
    assert envelope["schema"] == "lh.exec/v1"


def test_exec_sends_the_prompt_on_stdin(harness_config: Path) -> None:
    """argv is bounded by ARG_MAX; stdin is not."""
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([], prompt="the prompt travels here")

    assert envelope["output"] == "the prompt travels here"


def test_exec_normalises_cost_and_token_fields(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([])

    assert envelope["cost_usd"] == 0.5
    assert envelope["prompt_tokens"] == 1 + 2 + 3
    assert envelope["output_tokens"] == 4
    assert envelope["cache_creation_tokens"] == 2
    assert envelope["cache_read_tokens"] == 3
    assert envelope["num_turns"] == 1
    assert envelope["duration_ms"] == 5


def test_exec_reports_no_error_on_success(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([])

    assert envelope["error"] is None


# --- the harness block (which provider actually charged) -------------------


def test_exec_records_the_resolved_profile_and_binary(harness_config: Path) -> None:
    binary = _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--profile", "work"])

    harness = envelope["harness"]
    assert harness["profile"] == "work"
    assert harness["agent"] == "claude-code"
    assert harness["binary"] == str(binary)
    assert harness["config_dir"].endswith("cfg-work")
    assert harness["lh_version"]


def test_exec_marks_an_unmatched_cwd_as_a_fallback(harness_config: Path, tmp_path: Path) -> None:
    """The silent failure mode: correct only while the default stays right."""
    _write_agent(ECHO_AGENT)
    outside = tmp_path / "outside"
    outside.mkdir()

    runner = CliRunner()
    from lazy_harness.cli.exec_cmd import exec_cmd

    cwd = Path.cwd()
    os.chdir(outside)
    try:
        result = runner.invoke(exec_cmd, [], input="hi")
    finally:
        os.chdir(cwd)

    envelope = json.loads(result.stdout)
    assert envelope["harness"]["profile"] == "personal"
    assert envelope["harness"]["profile_source"] == "default-fallback"


def test_exec_marks_a_root_match(harness_config: Path, tmp_path: Path) -> None:
    _write_agent(ECHO_AGENT)

    cwd = Path.cwd()
    os.chdir(tmp_path / "work")
    try:
        code, envelope = _invoke([])
    finally:
        os.chdir(cwd)

    assert code == 0
    assert envelope["harness"]["profile_source"] == "root-match"


def test_exec_marks_an_explicit_profile(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--profile", "work"])

    assert envelope["harness"]["profile_source"] == "explicit"


def test_exec_exports_the_agent_config_dir_to_the_child(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--profile", "work"])

    assert envelope["raw"]["config_dir_seen"].endswith("cfg-work")


# --- exit codes ------------------------------------------------------------


def test_exec_mirrors_a_nonzero_agent_exit_code(harness_config: Path) -> None:
    _write_agent("import sys\nsys.stdin.read()\nprint('{}')\nsys.exit(3)\n")

    code, envelope = _invoke([])

    assert code == 3
    assert envelope["success"] is False
    assert envelope["exit_code"] == 3


def test_exec_refuses_an_unknown_profile_with_a_harness_error(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, envelope = _invoke(["--profile", "ghost"])

    assert code == 70
    assert envelope["success"] is False
    assert envelope["error"]["kind"] == "unknown-profile"


def test_exec_refuses_an_agent_that_cannot_run_headless(
    harness_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = harness_config / "config.toml"
    config.write_text(config.read_text().replace('type = "claude-code"', 'type = "null"'))

    code, envelope = _invoke([])

    assert code == 70
    assert envelope["error"]["kind"] == "agent-not-headless"


def test_exec_reports_a_missing_binary(
    harness_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(harness_config))  # no `claude` anywhere

    code, envelope = _invoke([])

    assert code == 70
    assert envelope["error"]["kind"] == "binary-not-found"


def test_exec_requires_a_prompt_on_stdin(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, envelope = _invoke([], prompt="   ")

    assert code == 70
    assert envelope["error"]["kind"] == "empty-prompt"


# --- argument separation ---------------------------------------------------


def test_exec_forwards_extra_args_after_the_separator(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--", "--verbose"])

    assert "--verbose" in envelope["raw"]["argv"]


def test_exec_does_not_swallow_an_agent_flag_that_collides_with_its_own(
    harness_config: Path,
) -> None:
    """`lh run` eats `--profile` before the agent sees it. After `--`, we must not."""
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--profile", "work", "--", "--profile", "agent-side"])

    assert envelope["harness"]["profile"] == "work"
    assert envelope["raw"]["argv"][-2:] == ["--profile", "agent-side"]


def test_exec_rejects_an_unknown_flag_before_the_separator(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, _ = _invoke(["--nonsense"])

    assert code == 2


# --- model tiers -----------------------------------------------------------


def test_exec_maps_a_tier_to_a_provider_model(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--tier", "fast"])

    argv = envelope["raw"]["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"


def test_exec_passes_an_explicit_model_through(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--model", "claude-opus-4-1-20250805"])

    argv = envelope["raw"]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-4-1-20250805"


def test_exec_sends_no_model_flag_when_neither_is_given(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([])

    assert "--model" not in envelope["raw"]["argv"]


def test_exec_rejects_a_tier_and_a_model_together(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, _ = _invoke(["--tier", "fast", "--model", "opus"])

    assert code == 2


def test_exec_rejects_an_unknown_tier(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, _ = _invoke(["--tier", "turbo"])

    assert code == 2


# --- the tool tri-state ----------------------------------------------------


def test_exec_leaves_tool_policy_alone_by_default(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([])

    argv = envelope["raw"]["argv"]
    assert "--allowedTools" not in argv
    assert "--disallowedTools" not in argv


def test_exec_denies_tools_by_name_for_no_tools(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--no-tools"])

    argv = envelope["raw"]["argv"]
    assert "Task" in argv[argv.index("--disallowedTools") + 1]


def test_exec_grants_a_named_tool_list(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke(["--allow-tools", "Read,Write"])

    argv = envelope["raw"]["argv"]
    assert argv[argv.index("--allowedTools") + 1] == "Read,Write"


def test_exec_rejects_an_empty_allow_tools_value(harness_config: Path) -> None:
    """`--allowedTools ''` silently grants the default reads. Refuse the ambiguity."""
    _write_agent(ECHO_AGENT)

    code, _ = _invoke(["--allow-tools", ""])

    assert code == 2


def test_exec_rejects_allow_tools_together_with_no_tools(harness_config: Path) -> None:
    _write_agent(ECHO_AGENT)

    code, _ = _invoke(["--allow-tools", "Read", "--no-tools"])

    assert code == 2


# --- dry run ---------------------------------------------------------------


def test_exec_dry_run_reports_the_plan_without_spawning(harness_config: Path) -> None:
    _write_agent("import sys; sys.exit(99)")

    code, envelope = _invoke(["--dry-run", "--tier", "deep"], prompt=None)

    assert code == 0
    assert envelope["dry_run"] is True
    assert envelope["harness"]["argv"][1:4] == ["-p", "--output-format", "json"]


# --- timeout and process-group teardown ------------------------------------

SPAWNER_AGENT = """
    import os, subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    open(os.environ["PIDFILE"], "w").write(str(child.pid))
    sys.stdin.read()
    time.sleep(120)
"""


def test_exec_times_out_with_its_own_exit_code(
    harness_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agent(SPAWNER_AGENT)
    monkeypatch.setenv("PIDFILE", str(tmp_path / "grandchild.pid"))

    code, envelope = _invoke(["--timeout", "1"])

    assert code == 124
    assert envelope["error"]["kind"] == "timeout"
    assert envelope["success"] is False


def test_exec_timeout_kills_the_whole_process_group(
    harness_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killing only the direct child leaves a grandchild burning tokens."""
    _write_agent(SPAWNER_AGENT)
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("PIDFILE", str(pidfile))

    _invoke(["--timeout", "1"])

    grandchild = int(pidfile.read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail(f"grandchild {grandchild} survived the timeout")


# --- real-process behaviour (fd-level, so not through CliRunner) -----------


def _run_cli(
    args: list[str], env: dict[str, str], prompt: str = "hi"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "from lazy_harness.cli.main import cli; cli()", *args],
        input=prompt,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _child_env(harness_config: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["LH_CONFIG_DIR"] = str(harness_config)
    env["COLUMNS"] = "400"
    return env


def test_exec_passes_agent_stderr_through_untouched(harness_config: Path) -> None:
    _write_agent(
        'import sys\nsys.stdin.read()\nsys.stderr.write("agent diagnostics\\n")\nprint("{}")\n'
    )

    proc = _run_cli(["exec"], _child_env(harness_config))

    assert "agent diagnostics" in proc.stderr
    assert json.loads(proc.stdout)["success"] is True


def test_exec_keeps_stdout_free_of_harness_chatter(harness_config: Path) -> None:
    """The consumer parses stdout; anything else there corrupts the envelope."""
    _write_agent(ECHO_AGENT)

    proc = _run_cli(["exec", "--profile", "ghost"], _child_env(harness_config))

    assert json.loads(proc.stdout)["error"]["kind"] == "unknown-profile"


def test_exec_and_run_resolve_the_same_profile_and_binary(harness_config: Path) -> None:
    """Two paths answering the same question must agree, end to end."""
    binary = _write_agent(ECHO_AGENT)
    env = _child_env(harness_config)

    run = _run_cli(["run", "--dry-run", "--profile", "work"], env)
    ex = _run_cli(["exec", "--dry-run", "--profile", "work"], env)

    harness = json.loads(ex.stdout)["harness"]
    assert harness["profile"] == "work"
    assert f"profile: {harness['profile']}" in run.stderr
    assert str(binary) in run.stderr
    assert harness["binary"] == str(binary)
    assert harness["config_dir"] in run.stderr


# --- provider neutrality ---------------------------------------------------


class FakeHeadlessAdapter:
    """A second, non-Claude headless agent. Different flags, different envelope."""

    @property
    def name(self) -> str:
        return "fake"

    def config_dir(self, profile_config_dir: str) -> Path:
        from lazy_harness.core.paths import expand_path

        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        return "FAKE_CONFIG_DIR"

    def resolve_binary(self) -> Path | None:
        return Path.home() / ".local" / "share" / "claude" / "versions" / "0.0.1-fake"

    def supported_hooks(self) -> list[str]:
        return []

    def generate_hook_config(self, hooks: dict) -> dict:
        return {}

    def generate_mcp_config(self, servers: dict) -> dict:
        return {}

    def global_config_link(self) -> Path | None:
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "", "logs": "", "queue": ""}

    def system_doc_name(self) -> str:
        return ""

    def process_name(self) -> str:
        return ""

    def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
        return explicit or {"fast": "tiny", "balanced": "mid", "deep": "big"}.get(tier or "")

    def headless_argv(self, *, model: str | None, allowed_tools: list[str] | None) -> list[str]:
        argv = ["--headless"]
        if model:
            argv += ["--llm", model]
        return argv

    def parse_headless_result(self, stdout: str, exit_code: int):
        from lazy_harness.agents.base import HeadlessResult

        data = json.loads(stdout)
        return HeadlessResult(
            success=exit_code == 0,
            output=data["text"],
            exit_code=exit_code,
            cost_usd=None,
            prompt_tokens=data["tokens_in"],
            output_tokens=data["tokens_out"],
            raw=data,
        )


def test_fake_adapter_satisfies_the_headless_protocol() -> None:
    from lazy_harness.agents.base import HeadlessAgent

    assert isinstance(FakeHeadlessAdapter(), HeadlessAgent)


def test_exec_is_not_wired_to_claude_specific_flags_or_fields(
    harness_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents import registry

    monkeypatch.setitem(registry._AGENTS, "fake", FakeHeadlessAdapter)
    config = harness_config / "config.toml"
    config.write_text(config.read_text().replace('type = "claude-code"', 'type = "fake"'))
    _write_agent(
        "import json, sys\n"
        "sys.stdin.read()\n"
        'print(json.dumps({"text": "from a different provider",'
        ' "tokens_in": 11, "tokens_out": 22}))\n'
    )

    code, envelope = _invoke(["--tier", "deep"])

    assert code == 0
    assert envelope["output"] == "from a different provider"
    assert envelope["prompt_tokens"] == 11
    assert envelope["cache_creation_tokens"] is None
    assert envelope["cost_usd"] is None


# --- workload attribution (ADR-037 D4) -------------------------------------

SESSION_ECHO_AGENT = """
    import json, sys
    sys.stdin.read()
    argv = sys.argv[1:]
    reported = ""
    if "--session-id" in argv:
        reported = argv[argv.index("--session-id") + 1]
    print(json.dumps({
        "is_error": False,
        "result": "ok",
        "session_id": reported,
        "argv": argv,
    }))
"""


def _attribution(tmp_path: Path) -> dict[str, str]:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "data" / "metrics.db")
    try:
        return db.attribution_map()
    finally:
        db.close()


@pytest.fixture
def metrics_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_exec_pins_a_session_id_in_the_agent_argv(
    harness_config: Path, metrics_data_dir: Path
) -> None:
    import uuid

    _write_agent(SESSION_ECHO_AGENT)

    _, envelope = _invoke(["--workload", "vault-pass"])

    argv = envelope["raw"]["argv"]
    assert "--session-id" in argv
    pinned = argv[argv.index("--session-id") + 1]
    uuid.UUID(pinned)  # raises if it is not a well-formed UUID


def test_exec_records_the_workload_against_the_pinned_session(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path
) -> None:
    _write_agent(SESSION_ECHO_AGENT)

    _, envelope = _invoke(["--workload", "vault-pass"])

    argv = envelope["raw"]["argv"]
    pinned = argv[argv.index("--session-id") + 1]
    assert _attribution(tmp_path) == {pinned: "vault-pass"}


def test_exec_mints_a_fresh_session_id_per_invocation(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path
) -> None:
    """A reused id is refused by the agent, so it must never be remembered."""
    _write_agent(SESSION_ECHO_AGENT)

    _invoke(["--workload", "one"])
    _invoke(["--workload", "two"])

    recorded = _attribution(tmp_path)
    assert len(recorded) == 2
    assert sorted(recorded.values()) == ["one", "two"]


def test_exec_reads_the_workload_from_the_environment(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lazy-vault contract is a binary string, so env is the other channel."""
    _write_agent(SESSION_ECHO_AGENT)
    monkeypatch.setenv("LH_WORKLOAD", "from-env")

    _invoke([])

    assert list(_attribution(tmp_path).values()) == ["from-env"]


def test_exec_records_nothing_without_a_workload(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path
) -> None:
    """No caller label means no row: the table must not grow on every run."""
    _write_agent(SESSION_ECHO_AGENT)

    _invoke([])

    assert _attribution(tmp_path) == {}


def test_exec_dry_run_records_nothing(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path
) -> None:
    _write_agent(SESSION_ECHO_AGENT)

    code, envelope = _invoke(["--workload", "vault-pass", "--dry-run"])

    assert code == 0
    assert envelope["dry_run"] is True
    assert _attribution(tmp_path) == {}


REPORTS_OTHER_SESSION_AGENT = """
    import json, sys
    sys.stdin.read()
    print(json.dumps({
        "is_error": False,
        "result": "ok",
        "session_id": "a-different-id",
        "argv": sys.argv[1:],
    }))
"""


def test_exec_reconciles_when_the_agent_reports_another_session_id(
    harness_config: Path, metrics_data_dir: Path, tmp_path: Path
) -> None:
    """An exit code is not proof the pin took effect."""
    _write_agent(REPORTS_OTHER_SESSION_AGENT)

    _invoke(["--workload", "vault-pass"])

    assert _attribution(tmp_path) == {"a-different-id": "vault-pass"}


def test_exec_survives_an_unwritable_attribution_store(
    harness_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attribution is bookkeeping; it must never fail the run it describes."""
    _write_agent(SESSION_ECHO_AGENT)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    monkeypatch.setenv("LH_DATA_DIR", str(blocker / "nested"))

    code, envelope = _invoke(["--workload", "vault-pass"])

    assert code == 0
    assert envelope["success"] is True


# --- cost provenance (ADR-038, C1-C3) --------------------------------------

COSTLESS_AGENT = """
    import json, sys
    sys.stdin.read()
    print(json.dumps({"is_error": False, "result": "ok"}))
"""


def test_exec_marks_a_passed_through_cost_as_the_agents_own(harness_config: Path) -> None:
    """The agent's figure and the harness pricing table disagree by design, so
    the envelope has to say which door the number came through."""
    _write_agent(ECHO_AGENT)

    _, envelope = _invoke([])

    assert envelope["cost_usd"] == 0.5
    assert envelope["cost_source"] == "agent"


def test_exec_leaves_cost_source_null_when_the_agent_reported_no_cost(
    harness_config: Path,
) -> None:
    """`cost_source` is non-null if and only if `cost_usd` is."""
    _write_agent(COSTLESS_AGENT)

    _, envelope = _invoke([])

    assert envelope["cost_usd"] is None
    assert envelope["cost_source"] is None


# Writes a real transcript at the pinned stem, then hangs so `--timeout` kills
# it. 200_000 input and 40_000 output tokens at claude-opus-4-6's rates are
# exactly $1.00 each, so a lost bucket shows as 1.0 rather than as a plausible
# total.
TIMEOUT_TRANSCRIPT_AGENT = """
    import json, os, sys, time
    argv = sys.argv[1:]
    session_id = argv[argv.index("--session-id") + 1]
    project = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "-fake-project")
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, session_id + ".jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": "2026-08-31T11:19:00"}) + "\\n")
        fh.write(json.dumps({
            "type": "assistant",
            "timestamp": "2026-08-31T11:19:01",
            "message": {
                "id": "msg_flushed",
                "model": "claude-opus-4-6",
                "usage": {"input_tokens": 200000, "output_tokens": 40000},
            },
        }) + "\\n")
    time.sleep(60)
"""


def test_exec_bills_a_timed_out_run_from_its_transcript(harness_config: Path) -> None:
    """The most expensive outcome `lh exec` has reported `cost_usd: null` while
    the ingest billed the same run. The transcript is written at the stem this
    command pinned before spawning, so the kill does not destroy the figure."""
    _write_agent(TIMEOUT_TRANSCRIPT_AGENT)

    code, envelope = _invoke(["--timeout", "1"])

    assert code == 124
    assert envelope["error"]["kind"] == "timeout"
    assert envelope["cost_usd"] == 2.0
    assert envelope["cost_source"] == "transcript"
    assert envelope["prompt_tokens"] == 200_000
    assert envelope["output_tokens"] == 40_000


# --- the mute failure (ADR-038, C4) ----------------------------------------

REFUSING_AGENT = """
    import sys
    sys.stdin.read()
    sys.stderr.write("Error: Session ID 925529e2 is already in use.\\n")
    sys.exit(1)
"""

GARBAGE_ON_SUCCESS_AGENT = """
    import sys
    sys.stdin.read()
    sys.stdout.write("not json at all")
"""


def test_exec_types_a_failure_that_left_nothing_on_stdout(harness_config: Path) -> None:
    """A refused session id exits 1 with an empty stdout. The envelope was
    well-formed but carried no `error`, so the consumer got `success=False`
    with a null kind and no exception — the failure arrived mute."""
    _write_agent(REFUSING_AGENT)

    code, envelope = _invoke([])

    assert code == 1
    assert envelope["success"] is False
    assert envelope["error"]["kind"] == "no-envelope"
    assert "stderr" in envelope["error"]["message"]


SELF_REPORTING_AGENT = """
    import json, sys
    sys.stdin.read()
    sys.stdout.write(json.dumps({
        "type": "result",
        "is_error": True,
        "result": "tool use rejected by policy",
        "session_id": "0f2b9a1c-0000-4000-8000-000000000000",
    }))
    sys.exit(1)
"""


def test_exec_types_a_failure_the_agent_reported_in_its_own_envelope(
    harness_config: Path,
) -> None:
    """The other half of the mute failure. `parse_headless_result` derives
    `success` from `exit_code == 0 and is_error is not True`, so an agent that
    reports its own failure in well-formed JSON lands on `success=False` with a
    populated `raw` — which `no-envelope`'s guard deliberately excludes. Left
    unnamed it is the same mute shape from the consumer's side: `success=False`,
    `error=None`, and an exit code matching none it branches on."""
    _write_agent(SELF_REPORTING_AGENT)

    code, envelope = _invoke([])

    assert code == 1
    assert envelope["success"] is False
    assert envelope["error"]["kind"] == "agent-error"
    assert envelope["output"] == "tool use rejected by policy"


def test_a_named_failure_never_overwrites_the_agents_own_output(
    harness_config: Path,
) -> None:
    """The kind is stamped alongside the agent's message, never over it: the
    cause of an `agent-error` is on stdout, unlike `no-envelope` where it went
    to stderr. A consumer reading `output` must still find what the agent said."""
    _write_agent(SELF_REPORTING_AGENT)

    _, envelope = _invoke([])

    assert "rejected by policy" in envelope["output"]
    assert envelope["error"]["kind"] != "no-envelope"


def test_exec_leaves_a_zero_exit_with_unparseable_stdout_alone(harness_config: Path) -> None:
    """Explicitly not covered by `no-envelope`: `parse_headless_result` derives
    success from the exit code when it cannot parse, and an `error` block on a
    successful envelope would contradict itself."""
    _write_agent(GARBAGE_ON_SUCCESS_AGENT)

    code, envelope = _invoke([])

    assert code == 0
    assert envelope["success"] is True
    assert envelope["error"] is None


HANGING_AGENT = """
    import sys, time
    sys.stdin.read()
    time.sleep(60)
"""


def test_exec_reports_no_cost_for_a_timeout_that_flushed_no_turn(harness_config: Path) -> None:
    """A kill landing before the first assistant turn leaves a transcript with
    no usage lines, or none at all. The ingest bills nothing for it, and a 0
    here would report the run as free rather than as unmeasured."""
    _write_agent(HANGING_AGENT)

    code, envelope = _invoke(["--timeout", "1"])

    assert code == 124
    assert envelope["cost_usd"] is None
    assert envelope["cost_source"] is None
    assert envelope["prompt_tokens"] is None
    assert envelope["output_tokens"] is None


def test_every_envelope_has_the_same_keys_whatever_the_outcome(
    harness_config: Path, tmp_path: Path
) -> None:
    """A consumer must not need a separate code path to read a timeout. The
    four `_emit` sites all build from one `_base_envelope()`; this asserts the
    property they are supposed to have rather than listing expected keys."""
    _write_agent(ECHO_AGENT)
    _, success = _invoke([])
    _, dry_run = _invoke(["--dry-run"])
    _, harness_error = _invoke(["--profile", "nonexistent"])

    _write_agent(HANGING_AGENT)
    _, timeout = _invoke(["--timeout", "1"])

    assert set(timeout) == set(success)
    assert set(dry_run) == set(success)
    assert set(harness_error) == set(success)
    assert "cost_source" in success


def test_a_timeout_reports_the_cost_fields_the_success_path_reports(
    harness_config: Path,
) -> None:
    """Identical keys, deliberately non-identical values: `num_turns` and
    `duration_ms` stay null on a timeout even when `cost_usd` carries a figure,
    so `cost_usd` implies nothing beyond `cost_source`."""
    _write_agent(TIMEOUT_TRANSCRIPT_AGENT)

    _, envelope = _invoke(["--timeout", "1"])

    assert envelope["cost_usd"] is not None
    assert envelope["cost_source"] == "transcript"
    assert envelope["num_turns"] is None
    assert envelope["duration_ms"] is None
