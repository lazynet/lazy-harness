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


def _in_lint_scope(root: Path, path: Path) -> bool:
    """Ansible-repo YAML isn't automatically Ansible YAML — a repo with an
    ansible.cfg can also carry unrelated configs (e.g. Traefik, Homepage) and
    encrypted vars. Only lint what the design (W2) actually targets: roles,
    playbooks, and files sitting directly in the Ansible root."""
    try:
        dir_parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return False
    if not dir_parts:
        return True
    return "roles" in dir_parts or dir_parts[0] == "playbooks"


def _is_vault_encrypted(path: Path) -> bool:
    """ansible-vault ciphertext isn't lintable YAML; feeding it to ansible-lint
    produces load-failure noise rather than a real finding."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline()
    except OSError:
        return False
    return first_line.startswith("$ANSIBLE_VAULT")


def _print_context(message: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": message,
                }
            }
        )
    )


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    raw = str(tool_input.get("file_path", ""))
    if not raw.endswith((".yml", ".yaml")):
        sys.exit(0)

    path = Path(raw)
    root = _find_ansible_root(path)
    if root is None:
        sys.exit(0)
    if not _in_lint_scope(root, path):
        sys.exit(0)
    if _is_vault_encrypted(path):
        sys.exit(0)

    try:
        result = subprocess.run(
            ["ansible-lint", str(path)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=ANSIBLE_LINT_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _log_unavailable(str(path), e)
        _print_context(
            f"ansible-lint is unavailable ({type(e).__name__}); {path.name} was left unchecked."
        )
        sys.exit(0)

    if result.returncode == 0:
        sys.exit(0)

    body = (result.stdout or result.stderr or "").strip()[:MAX_CONTEXT_CHARS]
    if not body:
        _write_hook_log(f"ansible-lint exited {result.returncode} with no output for {path}")
        sys.exit(0)

    _print_context(f"ansible-lint on {path.name}:\n{body}")
    sys.exit(0)


def _write_hook_log(message: str) -> None:
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.paths import agent_runtime_dir
        from lazy_harness.hooks.builtins._shared import make_log

        agent_dir = agent_runtime_dir(get_agent("claude-code"))
        log = make_log("post-tool-use-ansible-lint")
        log(agent_dir / "logs" / "hooks.log", message)
    except Exception:
        pass


def _log_unavailable(path: str, error: Exception) -> None:
    _write_hook_log(f"ansible-lint unavailable ({type(error).__name__}), left {path} unchecked")


if __name__ == "__main__":
    main()
