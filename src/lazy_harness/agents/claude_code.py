"""Claude Code agent adapter."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from lazy_harness.core.paths import expand_path


class ClaudeCodeAdapter:
    """Adapter for Claude Code (Anthropic's CLI agent)."""

    @property
    def name(self) -> str:
        return "claude-code"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        return "CLAUDE_CONFIG_DIR"

    def resolve_binary(self) -> Path | None:
        """Locate the claude binary.

        Preference order:
          1. ~/.local/share/claude/versions/<newest mtime> — Claude Code's
             version-manager dir, picks the most recently installed build.
          2. shutil.which('claude'), filtered to skip the lh entrypoint dir
             (so a `claude` shim that calls `lh run` cannot recurse).
        """
        versions_dir = Path.home() / ".local" / "share" / "claude" / "versions"
        if versions_dir.is_dir():
            candidates = [
                p for p in versions_dir.iterdir() if p.is_file() and os.access(p, os.X_OK)
            ]
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime)
        which = shutil.which("claude")
        if which:
            return Path(which)
        return None

    def supported_hooks(self) -> list[str]:
        return [
            "session_start",
            "session_stop",
            "pre_compact",
            "pre_tool_use",
            "post_tool_use",
            "notification",
        ]

    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate Claude Code settings.json hooks section."""
        hook_event_map = {
            "session_start": "SessionStart",
            "session_stop": "Stop",
            "pre_compact": "PreCompact",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "notification": "Notification",
        }
        settings_hooks: dict[str, list[dict]] = {}
        for event, scripts in hooks.items():
            cc_event = hook_event_map.get(event)
            if not cc_event:
                continue
            matchers = []
            for script in scripts:
                matchers.append(
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": script}],
                    }
                )
            settings_hooks[cc_event] = matchers
        return settings_hooks
