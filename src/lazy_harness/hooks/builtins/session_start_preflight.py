"""SessionStart preflight — reports what would strand a session partway through.

An expired login cost one whole session before this existed: the work was
already staged when the credential turned out to be dead. The other recorded
stranders are a git remote resolving to an unexpected identity and a tool
resolving to a second copy on `PATH`.

Reports, never blocks. `SessionStart` honours no verdict at all, so every path
returns an empty decision at worst and the worst outcome the reader sees is a
line saying the check could not tell.

Every check is scoped to the profile the hook was invoked under, which is the
whole point of the auth one: a preflight reporting some other profile's login
is the failure it exists to catch, not a smaller version of working.

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

**Which file, and whether it is the store, are both the adapter's business.**
The filename comes from `credentials_file()`, and `None` — an agent with no
file this check can parse — reports `n/a`, not `unknown`: "could not tell" and
"does not apply to this agent" are different findings and only one of them is
fixed by logging in again. On macOS the live Claude Code credential is in the
keychain and the file is a mirror nothing re-synchronises, so a verdict derived
from it is downgraded rather than trusted. Both are ADR-045.
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
from typing import Literal

# Module level, not under `TYPE_CHECKING`: `test_builtin_registry` resolves the
# signature with `typing.get_type_hints`, which evaluates the annotations
# against module globals and raises `NameError` on a name that only exists for
# the type checker. Importing here is also what takes a migrated module off
# `test_import_safety.GUARDED_HOOKS` — it is no longer invoked as a bare script,
# so the guarantee the ImportError guard carried moves to the runner's policy.
from lazy_harness.agents.base import AgentAdapter, HookDecision, HookEvent

Status = Literal["pass", "warn", "fail", "unknown", "n/a"]

# Below this much life left in the refresh token, say so before the session
# gets long enough to lose work to it.
_WARN_WITHIN_SECONDS = 12 * 3600

_STATUS_MARK = {"pass": "ok", "warn": "warn", "fail": "FAIL", "unknown": "?", "n/a": "n/a"}

#: Where an agent keeps the credential the file only mirrors. Keyed by platform
#: because the claim is about one agent's store on one operating system: macOS
#: having a keychain says nothing about an agent that never used it.
_MIRRORED_AGENTS_BY_PLATFORM: dict[str, frozenset[str]] = {"darwin": frozenset({"claude-code"})}

#: Said instead of a verdict the file cannot support. Names the store, so the
#: reader knows there is nothing to fix rather than a check to re-run.
_MIRROR_DETAIL = (
    "credentials live in the keychain on macOS; the file is a mirror the harness cannot verify"
)


@dataclass(frozen=True)
class Check:
    """One preflight result. `detail` is injected into the transcript."""

    name: str
    status: Status
    detail: str


def credentials_are_mirrored(agent: str, platform: str | None = None) -> bool:
    """True when this agent keeps the live credential somewhere this hook cannot read.

    Measured on 2026-09-16: a profile that had run `claude auth login` that
    morning showed a keychain entry hours old
    (`Claude Code-credentials-<sha256(config_dir) prefix>`) while
    `.credentials.json` still carried an eight-day-old mtime and an expired
    `refreshTokenExpiresAt`. The file opens, parses and has a valid shape, so no
    degradation branch applies and the check returned `fail` against a login
    that was healthy the whole time.

    The keychain is deliberately *not* read to settle it.
    `security find-generic-password` from launchd's Background domain — where a
    hook runs — has deleted a credential store on this machine twice. A check
    that admits a blind spot is usable; one that destroys credentials to remove
    it is not (ADR-045 D7).
    """
    return agent in _MIRRORED_AGENTS_BY_PLATFORM.get(platform or sys.platform, frozenset())


def auth_check(
    adapter: AgentAdapter,
    agent_dir: Path,
    *,
    now: float | None = None,
    platform: str | None = None,
) -> Check:
    """The auth verdict for the *invoked profile's* agent and directory.

    The directory half was closed first: a hook invoked with `--profile p` used
    to check whichever profile the ambient environment named, so the preflight
    could report a healthy login for a profile the session was not running
    under — exactly the failure this check exists to catch.

    This closes the other half. `.credentials.json` is a Claude Code filename;
    another adapter keeps its credentials elsewhere, or in a keychain with no
    file to read, so the name comes from `credentials_file()` and `None` is an
    answer rather than a missing file. Collapsing `None` into `unknown` would
    report the same thing for a broken login and for an agent whose login this
    check never knew how to look at.
    """
    name = adapter.credentials_file()
    if not name:
        return Check(
            "auth",
            "n/a",
            f"{adapter.name} exposes no credentials file this check can read",
        )
    return check_auth(
        agent_dir / name,
        now,
        mirrored=credentials_are_mirrored(adapter.name, platform),
    )


def check_auth(
    credentials_path: Path, now: float | None = None, *, mirrored: bool = False
) -> Check:
    """Report on the refresh token's remaining life, reading only the file.

    Returns `unknown` rather than `fail` for any shape this does not
    understand: reporting a healthy login as dead trains the reader to skip
    the whole block.

    `mirrored` says the file is a copy of a store this hook does not read, so
    an unhappy verdict derived from it is not evidence of an unhappy login.
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
    if mirrored and remaining <= _WARN_WITHIN_SECONDS:
        # `pass` deliberately survives this guard. A mirror is rewritten *from*
        # the store and never ahead of it, so a file claiming the refresh token
        # is good is a lower bound on the truth; a file claiming it is dead is
        # only evidence that nothing rewrote the file.
        return Check("auth", "unknown", _MIRROR_DETAIL)
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


def main(event: HookEvent) -> HookDecision:
    """Emit the preflight block. Abstains on every failure, including its own."""
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import agent_dir_for

        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        # Both halves of the pair are used now: the directory scopes the check
        # to the invoked profile, and the adapter names the file inside it — or
        # declines to, which is a verdict of its own.
        adapter, agent_dir = agent_dir_for(cfg, event.profile)

        # `parse_hook_input` yields `Path("")` — which is `Path(".")`, and
        # truthy — for a payload that names no cwd, so an `or Path.cwd()` would
        # not fire. `check_git_identity` shells out with this as the process's
        # working directory; `.` happens to resolve to the same place here, but
        # the fallback is kept explicit so this hook does not become the one
        # place in the fifteen where trap 1 is left to coincidence.
        cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

        checks = [
            auth_check(adapter, agent_dir),
            check_git_identity(str(cwd)),
            check_path_duplicates(),
        ]
        body = render(checks)
    except Exception:
        # Fail silent: a preflight bug must not disturb the session it precedes.
        # `SessionStart` honours no verdict at all (`claude_code.py:77`), so
        # there is nothing to fail open *into* — an empty decision is the only
        # thing this hook can return, and it is also the right one.
        return HookDecision()
    return HookDecision(additional_context=body) if body else HookDecision()
