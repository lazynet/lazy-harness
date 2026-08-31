"""Claude Code agent adapter."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from lazy_harness.agents.base import HeadlessResult, HookEntry
from lazy_harness.core.paths import expand_path

# Passing `--allowedTools ""` is a no-op: the CLI still grants its default read
# tools. Denying them by name is what actually pins a call to a single turn.
NO_TOOLS: tuple[str, ...] = (
    "Task",
    "Bash",
    "Glob",
    "Grep",
    "Read",
    "Edit",
    "Write",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
)

_TIER_MODELS: dict[str, str] = {
    "fast": "haiku",
    "balanced": "sonnet",
    "deep": "opus",
}


def _as_int(*candidates: object) -> int | None:
    """First candidate that is a real int. Unlike `or`, a legitimate 0 wins."""
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


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
            "session_end",
            "pre_compact",
            "post_compact",
            "pre_tool_use",
            "post_tool_use",
            "notification",
            "user_prompt_submit",
            "permission_request",
        ]

    def generate_hook_config(self, hooks: dict[str, list[str | HookEntry]]) -> dict:
        """Generate Claude Code settings.json hooks section.

        Each value can be a plain command string (uses the event's default
        matcher) or a `HookEntry` (overrides the matcher per-script).
        """
        hook_event_map = {
            "session_start": "SessionStart",
            "session_stop": "Stop",
            "session_end": "SessionEnd",
            "pre_compact": "PreCompact",
            "post_compact": "PostCompact",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "notification": "Notification",
            "user_prompt_submit": "UserPromptSubmit",
            "permission_request": "PermissionRequest",
        }
        matcher_map = {
            "pre_tool_use": "Bash",
            "post_tool_use": "Edit|Write",
        }
        settings_hooks: dict[str, list[dict]] = {}
        for event, scripts in hooks.items():
            cc_event = hook_event_map.get(event)
            if not cc_event:
                continue
            default_matcher = matcher_map.get(event, "")
            matchers = []
            for script in scripts:
                if isinstance(script, HookEntry):
                    command = script.command
                    matcher = script.matcher or default_matcher
                else:
                    command = script
                    matcher = default_matcher
                matchers.append(
                    {
                        "matcher": matcher,
                        "hooks": [{"type": "command", "command": command}],
                    }
                )
            settings_hooks[cc_event] = matchers
        return settings_hooks

    def global_config_link(self) -> Path | None:
        return Path.home() / ".claude"

    def mcp_config_file(self) -> str:
        return ".claude.json"

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "projects", "logs": "logs", "queue": "queue"}

    def system_doc_name(self) -> str:
        return "CLAUDE.md"

    def process_name(self) -> str:
        return "claude"

    # --- headless invocation (HeadlessAgent) ---

    def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
        """Map a tier to a CLI alias. An explicit id wins and is not validated."""
        if explicit:
            return explicit
        if tier is None:
            return None
        try:
            return _TIER_MODELS[tier]
        except KeyError:
            known = ", ".join(sorted(_TIER_MODELS))
            raise ValueError(f"unknown tier {tier!r} for claude-code (known: {known})") from None

    def headless_argv(self, *, model: str | None, allowed_tools: list[str] | None) -> list[str]:
        argv = ["-p", "--output-format", "json"]
        if model:
            argv += ["--model", model]
        if allowed_tools:
            argv += ["--allowedTools", ",".join(allowed_tools)]
        elif allowed_tools is not None:
            argv += ["--disallowedTools", ",".join(NO_TOOLS)]
        return argv

    def session_argv(self, session_id: str) -> list[str]:
        """Pin the conversation. A session id already in use is refused, not
        resumed: exit 1 with an empty stdout, so the caller must never reuse
        one."""
        return ["--session-id", session_id]

    def parse_headless_result(self, stdout: str, exit_code: int) -> HeadlessResult:
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            data = None
        if not isinstance(data, dict):
            return HeadlessResult(
                success=exit_code == 0,
                output=stdout,
                exit_code=exit_code,
                raw=None,
            )

        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        uncached = _as_int(usage.get("input_tokens"), data.get("input_tokens"))
        cache_creation = _as_int(usage.get("cache_creation_input_tokens"))
        cache_read = _as_int(usage.get("cache_read_input_tokens"))
        # `input_tokens` is only the uncached slice of the last turn — it reads
        # as single digits even on a 100k-token prompt. The input is the sum.
        prompt_tokens = (
            None
            if uncached is None and cache_creation is None and cache_read is None
            else (uncached or 0) + (cache_creation or 0) + (cache_read or 0)
        )

        # Claude Code's own figure, passed through verbatim — the harness
        # never recomputes it. It can disagree with `lh metrics` costs: as of
        # 2026-08-31 it bills claude-sonnet-5 at claude-sonnet-4-6's rates
        # ($3/$15 rather than $2/$10), over-reporting those sessions by 50%.
        # Recomputing it here would make the two agree by construction and
        # cost us the only signal we get when it is our own table that has
        # gone stale, so the disagreement is deliberate.
        cost = data.get("total_cost_usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            cost = data.get("cost_usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            cost = None

        result_text = data.get("result")
        session_id = data.get("session_id")
        return HeadlessResult(
            success=exit_code == 0 and data.get("is_error") is not True,
            output=result_text if isinstance(result_text, str) else stdout,
            exit_code=exit_code,
            cost_usd=float(cost) if cost is not None else None,
            duration_ms=_as_int(data.get("duration_ms")),
            prompt_tokens=prompt_tokens,
            output_tokens=_as_int(usage.get("output_tokens"), data.get("output_tokens")),
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            num_turns=_as_int(data.get("num_turns")),
            raw=data,
            session_id=session_id if isinstance(session_id, str) else None,
        )

    def generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        normalized: dict[str, dict] = {}
        for name, entry in servers.items():
            normalized[name] = {
                "command": entry["command"],
                "args": list(entry.get("args", [])),
            }
            if entry.get("env"):
                normalized[name]["env"] = dict(entry["env"])
        return {"mcpServers": normalized}
