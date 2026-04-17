from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomli_w

from lazy_harness.core.paths import contract_path
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


def run_wizard(answers: WizardAnswers, *, config_path: Path) -> None:
    """Write config.toml and create knowledge directory based on wizard answers."""
    data: dict = {
        "harness": {"version": "1"},
        "agent": {"type": answers.agent},
        "profiles": {
            "default": answers.profile_name,
            answers.profile_name: {
                "config_dir": f"~/.claude-{answers.profile_name}",
            },
        },
        "knowledge": {"path": contract_path(answers.knowledge_path)},
        "monitoring": {"enabled": True},
        "scheduler": {"backend": "auto"},
        "hooks": {
            "pre_tool_use": {
                "scripts": ["pre-tool-use-security"],
                "allow_patterns": [],
            },
            "post_tool_use": {
                "scripts": ["post-tool-use-format"],
            },
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(tomli_w.dumps(data).encode())
    answers.knowledge_path.mkdir(parents=True, exist_ok=True)
    (answers.knowledge_path / "sessions").mkdir(exist_ok=True)
    (answers.knowledge_path / "learnings").mkdir(exist_ok=True)
