"""The autouse isolation fixture must neutralise every agent's config-dir variable.

An agent session exports its own (`CODEX_HOME=~/.codex-lazy`), and the code under
test resolves runtime dirs through it, so a test that never opted in read the
host's live Engram metrics and failed on any machine whose real failure rate was
high. The fixture has to run against an environment that already holds the
variables, so the probe runs in a child pytest session.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lazy_harness.agents.registry import get_agent, list_agents

REPO_ROOT = Path(__file__).resolve().parents[2]


def _agent_env_vars() -> list[str]:
    return sorted({v for a in list_agents() if (v := get_agent(a).env_var())})


def test_the_isolation_fixture_clears_every_registered_agents_config_dir_var(
    tmp_path: Path,
) -> None:
    variables = _agent_env_vars()
    assert {"CLAUDE_CONFIG_DIR", "CODEX_HOME"} <= set(variables)

    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "conftest.py").write_text(
        "from tests.conftest import _isolate_agent_config_dir  # noqa: F401\n"
    )
    (probe / "test_probe.py").write_text(
        "import os\n"
        "import pytest\n\n"
        f"@pytest.mark.parametrize('name', {variables!r})\n"
        "def test_var_is_unset(name):\n"
        "    assert name not in os.environ\n"
    )
    env = {**os.environ, **{v: str(tmp_path / "host-runtime") for v in variables}}
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(probe)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
