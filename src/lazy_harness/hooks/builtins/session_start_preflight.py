"""SessionStart preflight — reports what would strand a session partway through.

An expired login cost one whole session before this existed: the work was
already staged when the credential turned out to be dead. The other recorded
stranders are a git remote resolving to an unexpected identity and a tool
resolving to a second copy on `PATH`.

Reports, never blocks. `SessionStart` has no blocking semantics, so every path
exits 0 and the worst outcome is a line saying the check could not tell.

**The auth check reads a file and spawns nothing.** Running the auth CLI from
inside a hook is what the operator's rules forbid: a credential helper that
cannot reach the keychain — as happens in launchd's Background domain — has
deleted a credential store before now. A read cannot do that.

It reads `refreshTokenExpiresAt`, not `expiresAt`. The access token expires
constantly and is refreshed transparently; measured on a live profile,
`expiresAt` was 61 hours in the past while the session worked perfectly,
because the refresh token still had 84 hours. Reading the wrong field makes
the check cry wolf on every session, and a preflight nobody reads is worse
than none.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Status = Literal["pass", "warn", "fail", "unknown"]

# Below this much life left in the refresh token, say so before the session
# gets long enough to lose work to it.
_WARN_WITHIN_SECONDS = 12 * 3600

_STATUS_MARK = {"pass": "ok", "warn": "warn", "fail": "FAIL", "unknown": "?"}


@dataclass(frozen=True)
class Check:
    """One preflight result. `detail` is injected into the transcript."""

    name: str
    status: Status
    detail: str


def _credentials_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / ".credentials.json"


def check_auth(credentials_path: Path, now: float | None = None) -> Check:
    """Report on the refresh token's remaining life, reading only the file.

    Returns `unknown` rather than `fail` for any shape this does not
    understand: reporting a healthy login as dead trains the reader to skip
    the whole block.
    """
    moment = time.time() if now is None else now
    try:
        raw = credentials_path.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return Check("auth", "unknown", "could not read the credentials file")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return Check("auth", "unknown", "credentials file is not valid JSON")

    if not isinstance(parsed, dict):
        return Check("auth", "unknown", "credentials file has an unexpected shape")

    oauth = parsed.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return Check("auth", "unknown", "credentials file has an unexpected shape")

    expires_at = oauth.get("refreshTokenExpiresAt")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return Check("auth", "unknown", "no refresh-token expiry recorded")

    remaining = expires_at / 1000 - moment
    if remaining <= 0:
        return Check(
            "auth",
            "fail",
            f"refresh token expired {abs(remaining) / 3600:.0f} h ago — "
            f"run `claude auth login` from a terminal before starting work",
        )
    if remaining <= _WARN_WITHIN_SECONDS:
        return Check("auth", "warn", f"refresh token expires in {remaining / 3600:.0f} h")
    return Check("auth", "pass", f"refresh token good for {remaining / 3600:.0f} h")


def _git(cwd: str, *args: str) -> str | None:
    """Run a read-only git command, returning None on any failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    out = getattr(proc, "stdout", "") or ""
    return out.strip() or None


def check_git_identity(cwd: str) -> Check:
    """Report the origin remote and the identity commits would carry."""
    remote = _git(cwd, "remote", "get-url", "origin")
    if remote is None:
        return Check("git", "unknown", "no origin remote resolved here")
    email = _git(cwd, "config", "user.email") or "unset"
    if email == "unset":
        return Check("git", "warn", f"{remote} — user.email is unset")
    return Check("git", "pass", f"{remote} as {email}")


def check_path_duplicates(tools: tuple[str, ...] = ("claude", "uv")) -> Check:
    """Report tools resolving to more than one copy on PATH.

    A second copy shadowing the pinned one is silent until it behaves
    differently, which is exactly when it is hardest to spot.
    """
    duplicated = []
    for tool in tools:
        seen: list[str] = []
        path_env = os.environ.get("PATH", "")
        for directory in path_env.split(os.pathsep):
            if not directory:
                continue
            candidate = shutil.which(tool, path=directory)
            if candidate and os.path.realpath(candidate) not in seen:
                seen.append(os.path.realpath(candidate))
        if len(seen) > 1:
            duplicated.append(f"{tool} ({len(seen)} copies)")
    if not duplicated:
        return Check("path", "pass", "no shadowed tools")
    return Check("path", "warn", "; ".join(duplicated))


def render(checks: list[Check]) -> str:
    """Render the block injected into the session.

    Clean runs collapse to one line. A preflight that prints a wall of green
    every session stops being read, and then the one red line is invisible.
    """
    if not checks:
        return ""
    noteworthy = [c for c in checks if c.status != "pass"]
    if not noteworthy:
        return "## Preflight\n\nAll clear: " + ", ".join(c.name for c in checks) + "."
    lines = ["## Preflight", ""]
    lines += [f"- **{c.name}** [{_STATUS_MARK[c.status]}] — {c.detail}" for c in noteworthy]
    passed = [c.name for c in checks if c.status == "pass"]
    if passed:
        lines.append(f"- Clear: {', '.join(passed)}.")
    return "\n".join(lines)


def _read_stdin_json() -> dict[str, Any]:
    """Read and parse stdin as JSON; return {} on any parse error or empty input."""
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


def main() -> None:
    """Emit the preflight block. Exits 0 on every path, including failure."""
    try:
        payload = _read_stdin_json()
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = os.getcwd()

        checks = [
            check_auth(_credentials_path()),
            check_git_identity(cwd),
            check_path_duplicates(),
        ]
        body = render(checks)
        if body:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": body,
                        }
                    }
                )
            )
    except Exception:
        # Fail silent: a preflight bug must not disturb the session it precedes.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
