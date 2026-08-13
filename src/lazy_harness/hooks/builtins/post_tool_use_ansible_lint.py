"""PostToolUse hook — runs `ansible-lint` on YAML edits inside Ansible repos.

Fail-soft: every error path exits 0, because a linter failure must never block
the agent. Results are emitted as additionalContext rather than logged, so the
agent actually sees them. See spec
`specs/designs/2026-08-13-agent-surface-adoption-design.md`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ANSIBLE_LINT_TIMEOUT_SECS = 30
MAX_CONTEXT_CHARS = 4000


def _read_stdin_json() -> dict[str, Any]:
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find_ansible_root(path: Path) -> Path | None:
    """Walk up looking for ansible.cfg. None means this is not an Ansible repo."""
    for parent in [path, *path.parents]:
        if (parent / "ansible.cfg").is_file():
            return parent
    return None


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    raw = str(payload.get("tool_input", {}).get("file_path", ""))
    if not raw.endswith((".yml", ".yaml")):
        sys.exit(0)

    path = Path(raw)
    if _find_ansible_root(path) is None:
        sys.exit(0)

    try:
        result = subprocess.run(
            ["ansible-lint", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=ANSIBLE_LINT_TIMEOUT_SECS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        _log_unavailable(str(path), e)
        sys.exit(0)

    if result.returncode == 0:
        sys.exit(0)

    body = (result.stdout or result.stderr or "").strip()[:MAX_CONTEXT_CHARS]
    if body:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"ansible-lint on {path.name}:\n{body}",
                    }
                }
            )
        )
    sys.exit(0)


def _log_unavailable(path: str, error: Exception) -> None:
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.paths import agent_runtime_dir
        from lazy_harness.hooks.builtins._shared import make_log

        agent_dir = agent_runtime_dir(get_agent("claude-code"))
        log = make_log("post-tool-use-ansible-lint")
        log(
            agent_dir / "logs" / "hooks.log",
            f"ansible-lint unavailable ({type(error).__name__}), left {path} unchecked",
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
