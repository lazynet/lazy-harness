"""PostToolUse hook — runs `ansible-lint` on YAML edits inside Ansible repos.

Fail-soft: every error path abstains, because a linter failure must never block
the agent. Results are returned as `additional_context` rather than logged, so
the agent actually sees them. See spec
`specs/designs/2026-08-13-agent-surface-adoption-design.md`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Module level, not under `TYPE_CHECKING`: `test_builtin_registry` resolves the
# signature with `typing.get_type_hints`, which evaluates the annotations
# against module globals and raises `NameError` on a name that only exists for
# the type checker.
from lazy_harness.agents.base import HookDecision, HookEvent

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
#
# It is also the gate itself, and stays so after the migration on purpose.
# `event.tool.operation is Operation.MODIFY_FILE` looks like the normalised
# spelling and is not: `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE`
# beside `Edit` and `Write` (`claude_code.py:97`), and `_FILE_PATH_KEYS` reads
# `notebook_path` into the same `FileEdit.path`. The `.yml`/`.yaml` re-check
# below does not narrow that back, because nothing in `ToolCall` makes a
# notebook's path end `.ipynb` — so swapping the gate would run `ansible-lint`
# on notebooks for the first time. Widening this hook's reach is a decision to
# take deliberately, not one to let ride in as a refactor.
INSPECTED_TOOLS = frozenset({"Edit", "Write"})

ANSIBLE_LINT_TIMEOUT_SECS = 30
MAX_CONTEXT_CHARS = 4000


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


def _lint(path: Path, profile: str) -> str | None:
    """Lint one edited file; the context to feed back, or None for silence."""
    root = _find_ansible_root(path)
    if root is None:
        return None
    if not _in_lint_scope(root, path):
        return None
    if _is_vault_encrypted(path):
        return None

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
        _write_hook_log(
            f"ansible-lint unavailable ({type(e).__name__}), left {path} unchecked", profile
        )
        return f"ansible-lint is unavailable ({type(e).__name__}); {path.name} was left unchecked."

    if result.returncode == 0:
        return None

    body = (result.stdout or result.stderr or "").strip()[:MAX_CONTEXT_CHARS]
    if not body:
        _write_hook_log(
            f"ansible-lint exited {result.returncode} with no output for {path}", profile
        )
        return None

    return f"ansible-lint on {path.name}:\n{body}"


def main(event: HookEvent) -> HookDecision:
    tool = event.tool
    # The native name rather than the operation — see `INSPECTED_TOOLS`.
    if tool is None or tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()

    # `edits` is plural because Codex's `apply_patch` and Copilot's `edit` can
    # touch several files in one call. Claude Code yields at most one, so this
    # loop is a single pass there; taking `edits[0]` instead would re-introduce
    # the singular `file_path` assumption the contract exists to remove.
    findings = [
        finding
        for edit in tool.edits
        # `endswith` on the string, not `Path.suffix`: a file named exactly
        # `.yml` has an empty suffix and a non-empty stem, so `suffix` would
        # silently stop inspecting one shape the pre-migration gate covered.
        if str(edit.path).endswith((".yml", ".yaml"))
        and (finding := _lint(edit.path, event.profile)) is not None
    ]
    if not findings:
        return HookDecision()
    return HookDecision(additional_context="\n\n".join(findings))


def _write_hook_log(message: str, profile: str) -> None:
    """Append one audit line under the *invoked profile's* agent directory.

    This used to be `get_agent("claude-code")` plus `agent_runtime_dir(agent)`
    with no profile, so a hook running under `--profile p` appended its line to
    whatever directory the global agent named. Measured before the fix: under
    `--profile gate` the line landed in `~/.claude/logs/hooks.log`.
    `tests/integration/test_hook_log_profile_isolation.py` holds both halves.
    """
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import agent_dir_for, make_log

        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        agent_dir = agent_dir_for(cfg, profile)[1]
        log = make_log("post-tool-use-ansible-lint")
        log(agent_dir / "logs" / "hooks.log", message)
    except Exception:  # noqa: BLE001 — an unwritable log must not lose the finding
        pass
