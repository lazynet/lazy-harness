from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomli_w

from lazy_harness.core.paths import contract_path
from lazy_harness.knowledge.directory import ensure_knowledge_dir
from lazy_harness.migrate.detector import detect_claude_code, detect_lazy_claudecode


class ExistingSetupError(Exception):
    """Raised when lh init is run on a system with an existing setup."""


def check_existing_setup(*, home: Path, lh_config: Path) -> None:
    """Raise ExistingSetupError if any pre-existing setup is detected.

    Checks, in order:
    1. An existing lazy-harness config.toml
    2. A vanilla Claude Code install at ~/.claude/
    3. lazy-claudecode multi-profile dirs (~/.claude-*)
    """
    if lh_config.is_file():
        raise ExistingSetupError(
            "lazy-harness is already configured. Use `lh init --force` "
            "to reinitialize (existing config will be backed up)."
        )
    cc = detect_claude_code(home / ".claude")
    if cc is not None:
        raise ExistingSetupError(
            "Detected existing Claude Code setup at ~/.claude/. "
            "To preserve your history, use `lh migrate` instead of `lh init`."
        )
    lc = detect_lazy_claudecode(home)
    if lc is not None:
        raise ExistingSetupError(
            f"Detected existing lazy-claudecode profiles: {', '.join(lc.profiles)}. "
            "Use `lh migrate` instead of `lh init`."
        )


@dataclass
class WizardAnswers:
    profile_name: str
    agent: str
    knowledge_path: Path
    enable_qmd: bool
    # ADR-050 rejects a per-agent billing default (a Codex profile can be a
    # subscription or a metered API key), so this stays "per_token" for every
    # agent unless the wizard prompt gets an explicit answer.
    billing_model: str = "per_token"


# The default `[agent].type` (`core.config.AgentConfig.type`) — not imported,
# to avoid a config.py <-> init.wizard cycle over one literal a schema change
# would already touch on both sides.
_DEFAULT_AGENT = "claude-code"

# `~/.<prefix>-<profile>` per agent, matching the shape `lh profile add`
# expects a caller to have already chosen (it takes `--config-dir` literally
# rather than deriving it). Not the adapter's registry key: "claude-code"
# would give `~/.claude-code-<name>`, and every profile on disk today is
# `~/.claude-<name>`.
_CONFIG_DIR_PREFIXES: dict[str, str] = {
    "claude-code": "claude",
    "codex": "codex",
    "copilot": "copilot",
}


def _config_dir_for(agent: str, profile_name: str) -> str:
    prefix = _CONFIG_DIR_PREFIXES.get(agent, agent)
    return f"~/.{prefix}-{profile_name}"


def run_wizard(answers: WizardAnswers, *, config_path: Path) -> None:
    """Write config.toml and create knowledge directory based on wizard answers."""
    profile_entry: dict = {
        "config_dir": _config_dir_for(answers.agent, answers.profile_name),
    }
    if answers.agent != _DEFAULT_AGENT:
        profile_entry["agent"] = answers.agent
    if answers.billing_model != "per_token":
        profile_entry["billing_model"] = answers.billing_model

    data: dict = {
        "harness": {"version": "1"},
        "agent": {"type": answers.agent},
        "profiles": {
            "default": answers.profile_name,
            answers.profile_name: profile_entry,
        },
        "knowledge": {"root": contract_path(answers.knowledge_path)},
        "monitoring": {"enabled": True},
        "scheduler": {"backend": "auto"},
        "hooks": {
            "pre_tool_use": {
                "scripts": ["pre-tool-use-security"],
                "allow_patterns": [],
            },
            "post_tool_use": {
                "scripts": ["post-tool-use-format", "post-tool-use-sync-system-doc"],
            },
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(tomli_w.dumps(data).encode())
    ensure_knowledge_dir(answers.knowledge_path)
