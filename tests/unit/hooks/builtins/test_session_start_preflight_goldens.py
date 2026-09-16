"""Byte goldens for `session-start-preflight`, captured before its migration.

This hook is one of the few in step 5 whose output channel a golden can
actually see: it writes `additionalContext` on stdout and nothing to disk. So
unlike the four log-only hooks of wave A — where every case froze to the same
empty triple and a `main()` returning `HookDecision()` reproduced all of them —
the cases here discriminate. One per branch of the *verdict*, not one happy
path: `render` collapses an all-clear run to a single line and gives every
non-passing check a line of its own, so the two shapes are different bytes.

**The one thing that cannot be frozen is the clock.** `check_auth` renders
`{remaining / 3600:.0f} h`, read from `time.time()` in the hook's own process,
so the hour count ticks over between the capture and every later run. It is
normalised out by the explicit rule in `_normalise_hours`, and the arithmetic
it hides is pinned instead by `TestCheckAuth`, which injects `now`. That split
is deliberate: the golden owns the channel and the wording, the unit test owns
the number.

**The platform cannot be pinned, so three cases carry two goldens.** ADR-045 D6
downgrades a file-derived `fail` or `warn` to `unknown` where the file is a
mirror of the keychain, which is macOS and only macOS. Normalising that away
would freeze the one property the branch exists to produce, so the affected
cases are keyed instead: the runner asserts its own platform's bytes, and the
committed bytes of *both* are asserted from either runner by the two named
tests below. CI runs Linux and macOS.

`GIT_CONFIG_NOSYSTEM` is pinned for the same reason `pinned_env` pins `PATH`.
`check_git_identity` shells out to `git config user.email`, and a machine
carrying one in `/etc/gitconfig` would turn the `git`-warn case into a pass —
the golden would then encode the capturing machine's git install.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lazy_harness.hooks.engine import CLI_BOOTSTRAP
from tests.unit.hooks.builtins._goldens import (
    HookRun,
    assert_golden,
    golden_path,
    pinned_env,
    run_through_runner,
)

HOOK = "session-start-preflight"

SESSION = "0193b0de-aaaa-bbbb-cccc-ddddeeeeffff"

#: A literal, so the golden does not encode the capturing machine's remotes.
ORIGIN = "https://github.com/example/preflight-fixture.git"
EMAIL = "fixture@example.invalid"

_CONFIG_MIN = '[harness]\nversion = "1"\n'

#: Fixed instants rather than offsets from `time.time()` wherever the branch
#: allows it: the pass and fail branches only need the sign of the difference,
#: and the hour figure they render is normalised away.
_FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z
_FAR_PAST_MS = 1_577_836_800_000  # 2020-01-01T00:00:00Z

#: The warn branch is the one exception. It is a *window* — `0 < remaining <=
#: 12 h` — so a fixed instant would fall out of it as the wall clock moved and
#: the case would silently become a pass or a fail. Three hours from capture
#: time sits nine hours clear of either edge.
_WARN_WITHIN_HOURS = 3.0


def _credentials(refresh_expires_at_ms: int | None) -> str:
    oauth: dict[str, object] = {"accessToken": "x", "refreshToken": "y"}
    if refresh_expires_at_ms is not None:
        oauth["refreshTokenExpiresAt"] = refresh_expires_at_ms
    return json.dumps({"claudeAiOauth": oauth})


@dataclass(frozen=True)
class Case:
    """One branch of the preflight's verdict."""

    id: str
    #: Body of `.credentials.json` in the resolved agent dir. `None` writes none.
    credentials: str | None = None
    #: Write credentials expiring this many hours from capture time instead,
    #: for the branch whose verdict is a window rather than a sign.
    expires_in_hours: float | None = None
    #: Make the cwd a git repository at all.
    git_repo: bool = False
    #: Give that repository an `origin` remote.
    git_origin: bool = True
    #: Set `user.email` locally in it.
    git_email: bool = True
    #: Put two distinct `claude` shims on PATH, so `check_path_duplicates` warns.
    shadow_claude: bool = False
    #: Name `cwd` in the payload. `False` is trap 1's input.
    declare_cwd: bool = True
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


_HEALTHY = _credentials(_FAR_FUTURE_MS)
_EXPIRED = _credentials(_FAR_PAST_MS)

CASES: list[Case] = [
    # `render`'s collapsed branch: every check passes, so the block is one line.
    Case(id="all-clear", credentials=_HEALTHY, git_repo=True),
    # The branch the operator is living in right now, and the reason this hook
    # exists: a dead refresh token reported before the work is staged.
    Case(id="auth-expired", credentials=_EXPIRED, git_repo=True),
    Case(id="auth-expiring-soon", expires_in_hours=_WARN_WITHIN_HOURS, git_repo=True),
    Case(id="auth-unknown-no-credentials-file", git_repo=True),
    Case(id="auth-unknown-credentials-malformed", credentials="not json", git_repo=True),
    Case(
        id="auth-unknown-no-expiry-recorded",
        credentials=_credentials(None),
        git_repo=True,
    ),
    # `check_git_identity`'s two non-passing branches.
    Case(id="git-unknown-not-a-repository", credentials=_HEALTHY),
    Case(id="git-warn-email-unset", credentials=_HEALTHY, git_repo=True, git_email=False),
    Case(
        id="git-unknown-repository-without-an-origin",
        credentials=_HEALTHY,
        git_repo=True,
        git_origin=False,
    ),
    Case(
        id="path-warn-two-copies-of-claude",
        credentials=_HEALTHY,
        git_repo=True,
        shadow_claude=True,
    ),
    # Every non-passing check at once: the multi-line branch of `render` with
    # no `Clear:` tail, which no single-check case reaches.
    Case(id="everything-noteworthy", credentials=_EXPIRED, shadow_claude=True),
    # Trap 1: `parse_hook_input` yields `Path("")` — which is `Path(".")`, and
    # truthy — for a payload naming no cwd.
    Case(id="cwd-absent-from-the-payload", credentials=_HEALTHY, git_repo=True, declare_cwd=False),
    Case(id="stdin-empty", credentials=_HEALTHY, git_repo=True, raw_stdin=""),
    Case(id="stdin-malformed-json", credentials=_HEALTHY, git_repo=True, raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration `_read_stdin_json` degraded them to `{}` and ran the hook against
#: `os.getcwd()`, which is why these two goldens are the licensed divergence.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})

#: Whether the agent under test keeps its live credential off the filesystem.
_MIRRORED = sys.platform == "darwin"


def _is_mirror_sensitive(case: Case) -> bool:
    """Whether this case's auth verdict comes from the file's expiry.

    Derived from the fixture rather than listed beside it: a new case planting
    an expired file would otherwise keep asserting the Linux golden on macOS and
    fail with a diff nobody could read as "you forgot to capture the pair".
    """
    return case.credentials == _EXPIRED or case.expires_in_hours is not None


def _case_id(case: Case) -> str:
    """The golden this platform must match for `case`."""
    return f"{case.id}-darwin" if _MIRRORED and _is_mirror_sensitive(case) else case.id


@dataclass
class World:
    """The tmp tree one case runs in."""

    work: Path
    agent_dir: Path
    global_agent_dir: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repo(work: Path, *, origin: bool, email: bool) -> None:
    _git(work, "init", "-b", "main")
    if origin:
        _git(work, "remote", "add", "origin", ORIGIN)
    if email:
        _git(work, "config", "user.email", EMAIL)


def _shim(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("#!/bin/sh\nexit 0\n")
    target.chmod(0o755)


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree.

    `work` is realpath'd for the reason task 4 and task 6 both recorded:
    `Path.cwd()` is symlink-resolved and a payload's `cwd` is not, so an
    unresolved `tmp_path` lets the pre-migration run (which reads `os.getcwd()`)
    and the migrated one (which reads `event.cwd`) differ invisibly.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**: `agent_runtime_dir` resolves the adapter's env var
    above the profile's `config_dir` (ADR-032 L3, `core/paths.py:176-183`), so
    leaving it set makes both answers the same path and no per-profile
    assertion can fail.
    """
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    env_agent_dir = tmp_path / "claude-global"
    global_agent_dir = home / ".claude" if profile else env_agent_dir
    agent_dir = tmp_path / f"claude-{profile}" if profile else env_agent_dir
    for d in (home, config_dir, data_dir, work, agent_dir, env_agent_dir):
        d.mkdir(parents=True, exist_ok=True)
    work = work.resolve()

    config = _CONFIG_MIN
    if profile is not None:
        config += f'\n[profiles.{profile}]\nconfig_dir = "{agent_dir}"\nroots = ["~"]\n'
    (config_dir / "config.toml").write_text(config)

    if case.expires_in_hours is not None:
        expiry = int((time.time() + case.expires_in_hours * 3600) * 1000)
        (agent_dir / ".credentials.json").write_text(_credentials(expiry))
    elif case.credentials is not None:
        (agent_dir / ".credentials.json").write_text(case.credentials)

    if case.git_repo:
        _make_repo(work, origin=case.git_origin, email=case.git_email)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
        # A `user.email` in `/etc/gitconfig` would turn the git-warn case into
        # a pass, encoding the capturing machine's git install in the golden.
        extra={"GIT_CONFIG_NOSYSTEM": "1"},
    )
    if case.shadow_claude:
        first = tmp_path / "bin-a"
        second = tmp_path / "bin-b"
        _shim(first, "claude")
        _shim(second, "claude")
        env["PATH"] = f"{first}:{second}:{env['PATH']}"
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {"hook_event_name": "SessionStart", "session_id": SESSION}
        if case.declare_cwd:
            payload["cwd"] = str(work)
        stdin = json.dumps(payload)

    return World(
        work=work, agent_dir=agent_dir, global_agent_dir=global_agent_dir, env=env, stdin=stdin
    )


#: The clock, and only the clock. `check_auth` renders a whole-hour figure
#: derived from `time.time()`, so the digits tick between the capture and every
#: later run; everything around them — the marker, the check name, the wording,
#: the direction of the comparison — stays frozen. A regression from "expired
#: N h ago" to "expires in N h" is still a golden diff. The number itself is
#: covered by `TestCheckAuth`, which injects `now`.
_HOURS = re.compile(r"\b\d+ h\b")


def _normalise_hours(run: HookRun) -> HookRun:
    return HookRun(
        stdout=_HOURS.sub("<N> h", run.stdout),
        stderr=_HOURS.sub("<N> h", run.stderr),
        exit_code=run.exit_code,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert_golden(HOOK, _case_id(case), _normalise_hours(run))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_no_golden_leaks_a_path_from_the_machine_that_captured_it(tmp_path: Path) -> None:
    """Every case's bytes are reproducible off this repo alone.

    `check_git_identity` puts a remote URL and an email on the channel, and
    `check_path_duplicates` could have put a resolved binary path there. The
    fixtures pin all three to literals; this asserts nothing else got in.
    """
    for case in CASES:
        golden = json.loads(golden_path(HOOK, _case_id(case)).read_text())
        blob = golden["stdout"] + golden["stderr"]
        assert "/Users/" not in blob, case.id
        assert "/home/" not in blob, case.id
        assert str(tmp_path.parent) not in blob, case.id


def test_an_all_clear_run_collapses_to_one_line() -> None:
    """The quiet branch, named rather than left implicit in a golden file.

    A preflight that prints a wall of green every session stops being read, and
    then the one red line is invisible. This is what keeps that property from
    being re-captured away.
    """
    golden = json.loads(golden_path(HOOK, "all-clear").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]

    assert golden["exit_code"] == 0
    assert body == "## Preflight\n\nAll clear: auth, git, path."


def test_the_expired_branch_names_the_check_and_the_remedy() -> None:
    """The line the operator is actually seeing, frozen as bytes.

    `[FAIL]` rather than `[?]` matters: `unknown` is what an unreadable file
    reports, and conflating the two is what trains a reader to skip the block.

    Asserted against the committed golden rather than a live run, so both halves
    of the platform pair are checked from either runner.
    """
    golden = json.loads(golden_path(HOOK, "auth-expired").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]

    assert golden["exit_code"] == 0
    assert "- **auth** [FAIL] — refresh token expired <N> h ago" in body
    assert "claude auth login" in body
    assert "- Clear: git, path." in body


def test_the_expired_branch_on_a_mirror_says_so_instead_of_failing() -> None:
    """The macOS half of the same pair — the false FAIL this change removes.

    Measured 2026-09-16: a profile logged in that morning reported
    `auth [FAIL] — refresh token expired 33 h ago` while the keychain entry was
    hours old and the login worked. The file is a mirror nothing rewrites, so
    the honest answer names the store rather than the expiry, and the remedy
    line is gone — there is nothing for the reader to re-run.
    """
    golden = json.loads(golden_path(HOOK, "auth-expired-darwin").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]

    assert golden["exit_code"] == 0
    assert "- **auth** [?] — credentials live in the keychain on macOS" in body
    assert "[FAIL]" not in body
    assert "claude auth login" not in body
    assert "- Clear: git, path." in body


def test_every_mirror_sensitive_case_carries_both_goldens() -> None:
    """Neither runner can capture the other's bytes, so absence must be loud.

    Without this, a case captured on one platform alone fails on the other with
    "golden was never captured", which reads as a harness fault rather than as
    the missing half of a deliberate pair.
    """
    sensitive = [c for c in CASES if _is_mirror_sensitive(c)]

    assert sensitive, "the fixture no longer exercises a file-derived verdict"
    for case in sensitive:
        assert golden_path(HOOK, case.id).is_file(), case.id
        assert golden_path(HOOK, f"{case.id}-darwin").is_file(), case.id


def test_an_unreadable_credentials_file_reports_unknown_and_never_fail() -> None:
    """Across all three of the shapes `check_auth` does not understand."""
    for case_id in (
        "auth-unknown-no-credentials-file",
        "auth-unknown-credentials-malformed",
        "auth-unknown-no-expiry-recorded",
    ):
        golden = json.loads(golden_path(HOOK, case_id).read_text())
        body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]
        assert "- **auth** [?] — " in body, case_id
        assert "[FAIL]" not in body, case_id


def test_no_golden_carries_a_token_value() -> None:
    """The block is injected into the transcript; the fixtures plant tokens."""
    for case in CASES:
        golden = json.loads(golden_path(HOOK, _case_id(case)).read_text())
        blob = golden["stdout"] + golden["stderr"]
        assert '"accessToken"' not in blob, case.id
        assert "refreshToken" not in blob, case.id


def _run(world: World, *, profile: str) -> HookRun:
    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", HOOK, "--profile", profile],
        input=world.stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(world.work),
        env=world.env,
        timeout=60,
        check=False,
    )
    return HookRun(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def _plant(directory: Path, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".credentials.json").write_text(body)


def _context(run: HookRun) -> str:
    assert run.exit_code == 0, run.stderr
    assert run.stdout.strip(), run.stderr
    body = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
    assert isinstance(body, str)
    return body


def test_the_auth_check_reads_the_invoked_profiles_credentials(tmp_path: Path) -> None:
    """Defect F7 in its second spelling, and the reason this task exists.

    `_credentials_path` — the helper `auth_check` replaced — resolved
    `CLAUDE_CONFIG_DIR` itself and fell back to
    `~/.claude` — "resolve globally, ignore the profile", the same shape PR #300
    fixed for `hooks.log` wearing a different mask. A hook invoked with
    `--profile gate` checked whichever profile the ambient environment named, so
    the preflight could report a healthy login for a profile the session was not
    running under: exactly the failure the check exists to catch. It is not a
    `get_agent` call, so the task 21 audit would never have seen it.

    The two directories carry *opposite* verdicts, which is what makes this a
    test. Clearing the env var alone is not enough — `agent_runtime_dir`'s last
    resort is `~/.claude`, a real directory the hook is entitled to read, so a
    run against an empty one reports `unknown` and looks like a first run.
    """
    case = next(c for c in CASES if c.id == "all-clear")
    world = _build(tmp_path, case, profile="gate")
    _plant(world.agent_dir, _EXPIRED)
    _plant(world.global_agent_dir, _HEALTHY)

    body = _context(_run(world, profile="gate"))

    # The verdict's *wording* is the platform's; what this test measures is
    # which directory produced it. Both spellings are unhappy and the healthy
    # one collapses to "All clear", so the pair still carries opposite answers.
    unhappy = (
        "- **auth** [?] — credentials live in the keychain on macOS"
        if _MIRRORED
        else "- **auth** [FAIL] — refresh token expired"
    )
    assert unhappy in body
    assert "All clear" not in body


def test_the_auth_check_does_not_report_the_global_dirs_verdict(tmp_path: Path) -> None:
    """The same pair with the verdicts swapped, so neither can pass by accident.

    Without it, a hook that had regressed to reporting `fail` unconditionally
    would satisfy the test above. Here the profile is healthy and the global
    directory is the dead one, and the healthy answer is the one that must win.
    """
    case = next(c for c in CASES if c.id == "all-clear")
    world = _build(tmp_path, case, profile="gate")
    _plant(world.agent_dir, _HEALTHY)
    _plant(world.global_agent_dir, _EXPIRED)

    body = _context(_run(world, profile="gate"))

    assert body == "## Preflight\n\nAll clear: auth, git, path."


def test_the_adapters_env_var_still_outranks_the_profiles_config_dir(tmp_path: Path) -> None:
    """The residual this migration does *not* close, pinned rather than implied.

    `agent_runtime_dir` resolves the adapter's env var above the profile's own
    `config_dir` (ADR-032 L3, `core/paths.py:176-183`), and `agent_dir_for`
    inherits that order. So with `CLAUDE_CONFIG_DIR` set, `--profile gate` still
    reads the directory the environment names — measured, not assumed:

        env set,   profile_config_dir=/tmp/gate -> /tmp/other-profile
        env unset, profile_config_dir=/tmp/gate -> /private/tmp/gate
        env unset, no profile                   -> ~/.claude

    That is the documented resolution order and not a defect of this hook; it is
    asserted here so that a later change to `agent_runtime_dir` cannot silently
    alter which credentials a preflight reads.
    """
    case = next(c for c in CASES if c.id == "all-clear")
    world = _build(tmp_path, case, profile="gate")
    env_named = tmp_path / "claude-from-the-environment"
    _plant(world.agent_dir, _EXPIRED)
    _plant(env_named, _HEALTHY)
    world.env["CLAUDE_CONFIG_DIR"] = str(env_named)

    body = _context(_run(world, profile="gate"))

    assert body == "## Preflight\n\nAll clear: auth, git, path."


def test_the_preflight_writes_nothing_outside_the_invoked_profile(tmp_path: Path) -> None:
    """Recipe step 7's absence half, for a hook that writes nothing at all.

    The other fourteen prove isolation through a `hooks.log` line; this one has
    no such line to place, so the assertion is the stronger one — the run leaves
    the global agent directory exactly as it found it, including not creating it.
    A hook that had started logging into `~/.claude` would fail here.
    """
    case = next(c for c in CASES if c.id == "all-clear")
    world = _build(tmp_path, case, profile="gate")
    _plant(world.agent_dir, _HEALTHY)
    before = (
        {p for p in world.global_agent_dir.rglob("*")} if world.global_agent_dir.exists() else set()
    )

    run = _run(world, profile="gate")

    assert run.exit_code == 0, run.stderr
    after = (
        {p for p in world.global_agent_dir.rglob("*")} if world.global_agent_dir.exists() else set()
    )
    assert after == before, sorted(after - before)


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The only two goldens this migration did not keep byte-identical, named.

    Twelve of the fourteen cases matched their pre-migration capture exactly.
    These two are decision 3's informational column: the runner refuses a
    payload it cannot parse *before* the builtin is reached, where
    `_read_stdin_json` used to degrade it to `{}` and run the checks anyway.
    What the pre-migration bytes carried, recorded here because the file no
    longer does:

        {"exit_code": 0, "stderr": "",
         "stdout": "{\\"hookSpecificOutput\\": {\\"hookEventName\\":
                     \\"SessionStart\\", \\"additionalContext\\":
                     \\"## Preflight\\\\n\\\\nAll clear: auth, git, path.\\"}}\\n"}

    That run is the improvement being traded for, not a loss: with no payload
    the old hook fell back to `os.getcwd()`, so the `git` line it reported
    described whatever directory the agent happened to spawn the hook from
    rather than the session's. A preflight reporting the wrong repository's
    identity is worse than one saying nothing.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")
