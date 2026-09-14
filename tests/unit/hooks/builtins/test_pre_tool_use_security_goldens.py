"""Byte goldens for `pre_tool_use_security`, one per branch, captured pre-migration.

This is the hook the design names first when it says a golden without stderr
covers nothing: every refusal here is a stderr write plus exit 2, and stdout
stays empty throughout. The branches below are read off `main()`, `should_block`
and `should_block_path` rather than guessed:

* payload shape — empty stdin, malformed stdin, JSON that is not an object, and
  a tool the hook does not inspect (all four abstain);
* one case per `BLOCK_RULE`, because the loop tries each in order and the
  matched rule decides the stderr bytes, plus the over-length match that gets
  the `…` ellipsis;
* the allowlist: a rescue, an invalid user regex, malformed TOML, a non-list
  value and a missing section — the last four all fall back to blocking;
* one case per `SECRET_PATH_GLOB` and per `SECRET_PATH_EXCEPTION`, on each of
  the four file tools, plus the empty-path and relative-path resolutions;
* abstention — the no-objection branch, asserted separately to emit *nothing*.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_builtin,
    short_temp_root,
)

HOOK = "pre-tool-use-security"
MODULE = "lazy_harness.hooks.builtins.pre_tool_use_security"


@dataclass(frozen=True)
class Case:
    """One branch: what goes in on stdin, and what the machine looks like."""

    id: str
    stdin: str
    config: str | None = None
    #: `True` when the hook expands `~` into the output, which is per-machine.
    normalise_home: bool = False
    #: `True` when the hook resolves a relative path against cwd.
    normalise_cwd: bool = False
    #: `True` when the case's paths must stay under the hook's 120-char cut.
    short_paths: bool = False


def _payload(tool: str, **tool_input: str) -> str:
    return json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    )


def _bash(command: str, *, case_id: str, config: str | None = None, **kw: bool) -> Case:
    return Case(id=case_id, stdin=_payload("Bash", command=command), config=config, **kw)


def _read(path: str, *, case_id: str, **kw: bool) -> Case:
    return Case(id=case_id, stdin=_payload("Read", file_path=path), **kw)


# --- payload shape -------------------------------------------------------- #

SHAPE_CASES: list[Case] = [
    Case(id="stdin-empty", stdin=""),
    Case(id="stdin-whitespace-only", stdin="   \n"),
    Case(id="stdin-malformed-json", stdin="not json at all"),
    Case(id="stdin-json-array-not-object", stdin="[1, 2, 3]"),
    Case(id="tool-not-inspected", stdin=_payload("WebFetch", url="https://example.com")),
    Case(id="tool-name-absent", stdin=json.dumps({"hook_event_name": "PreToolUse"})),
]

# --- one per BLOCK_RULE, in declaration order ----------------------------- #

RULE_CASES: list[Case] = [
    _bash("rm -rf ./build", case_id="rule-filesystem-recursive-delete"),
    _bash("truncate -s 0 app.log", case_id="rule-filesystem-truncate"),
    _bash("git push --force origin main", case_id="rule-git-force-push"),
    _bash("git reset --hard HEAD~1", case_id="rule-git-hard-reset"),
    _bash("git add -f .env", case_id="rule-git-forced-add-secret"),
    _bash('psql -c "DROP TABLE users"', case_id="rule-sql-destruction"),
    _bash("terraform destroy", case_id="rule-terraform-destroy"),
    _bash("terraform apply -auto-approve", case_id="rule-terraform-auto-approve"),
    _bash("terraform apply -replace=aws_instance.web", case_id="rule-terraform-replace"),
    _bash("terraform state rm aws_s3_bucket.logs", case_id="rule-terraform-state-mutation"),
    _bash("cat .env", case_id="rule-credentials-dotenv"),
    _bash("cat ~/.ssh/id_ed25519", case_id="rule-credentials-ssh-private-key"),
    _bash("cat ~/.aws/credentials", case_id="rule-credentials-aws"),
    _bash("cat server.pem", case_id="rule-credentials-cert-key"),
    # Over MAX_MATCH_LEN: the message keeps 120 characters and appends `…`.
    _bash("rm -rf ./" + "a" * 200, case_id="rule-match-truncated-at-max-len"),
]

# --- allowlist ------------------------------------------------------------ #

_ALLOW_WORKTREES = '[hooks.pre_tool_use]\nallow_patterns = ["\\\\.worktrees/"]\n'
_ALLOW_BROKEN_REGEX = '[hooks.pre_tool_use]\nallow_patterns = ["[unclosed"]\n'
_ALLOW_NOT_A_LIST = '[hooks.pre_tool_use]\nallow_patterns = "rm"\n'
_ALLOW_MISSING_SECTION = '[harness]\nversion = "1"\n'
_MALFORMED_TOML = "[hooks.pre_tool_use\nallow_patterns = ["

ALLOWLIST_CASES: list[Case] = [
    _bash(
        "rm -rf ./.worktrees/feat",
        case_id="allowlist-rescues-the-command",
        config=_ALLOW_WORKTREES,
    ),
    _bash(
        "rm -rf ./build",
        case_id="allowlist-invalid-regex-still-blocks",
        config=_ALLOW_BROKEN_REGEX,
    ),
    _bash("rm -rf ./build", case_id="allowlist-malformed-toml", config=_MALFORMED_TOML),
    _bash("rm -rf ./build", case_id="allowlist-not-a-list", config=_ALLOW_NOT_A_LIST),
    _bash("rm -rf ./build", case_id="allowlist-missing-section", config=_ALLOW_MISSING_SECTION),
    # The allowlist never reaches paths: a pattern wide enough for a command
    # would exempt every secret underneath it.
    Case(
        id="allowlist-does-not-rescue-a-path",
        stdin=_payload("Read", file_path="/srv/.worktrees/feat/.env"),
        config=_ALLOW_WORKTREES,
    ),
]

# --- one per SECRET_PATH_GLOB, in declaration order ----------------------- #

GLOB_CASES: list[Case] = [
    _read("/srv/app/.env", case_id="glob-dotenv"),
    _read("/srv/app/.env.production", case_id="glob-dotenv-suffixed"),
    _read("/srv/app/.dev.vars", case_id="glob-dev-vars"),
    _read("/srv/app/.dev.vars.prod", case_id="glob-dev-vars-suffixed"),
    _read("/srv/app/server.pem", case_id="glob-pem"),
    _read("/srv/app/tls.key", case_id="glob-key"),
    _read("/srv/app/id_rsa", case_id="glob-id-rsa"),
    _read("/srv/app/id_ed25519", case_id="glob-id-ed25519"),
    _read("/srv/app/secrets/token.txt", case_id="glob-secrets-dir"),
    _read("/srv/app/credentials/aws.json", case_id="glob-credentials-dir"),
    _read("/srv/app/.aws/config", case_id="glob-aws-dir"),
    _read("/srv/app/.ssh/known_hosts", case_id="glob-ssh-dir"),
    _read("/srv/app/.gnupg/pubring.kbx", case_id="glob-gnupg-dir"),
    _read("/srv/app/config/database.yml", case_id="glob-database-yml"),
    _read("/srv/app/config/credentials.json", case_id="glob-credentials-json"),
    _read("/srv/app/.npmrc", case_id="glob-npmrc"),
    _read("/srv/app/.pypirc", case_id="glob-pypirc"),
    _read("/srv/app/.netrc", case_id="glob-netrc"),
]

# --- one per SECRET_PATH_EXCEPTION ---------------------------------------- #

EXCEPTION_CASES: list[Case] = [
    _read("/srv/app/.ssh/id_ed25519.pub", case_id="exception-public-key"),
    _read("/srv/app/.env.example", case_id="exception-dotenv-example"),
    _read("/srv/app/.env.sample", case_id="exception-dotenv-sample"),
    _read("/srv/app/.env.template", case_id="exception-dotenv-template"),
]

# --- path resolution and the other file tools ----------------------------- #

PATH_CASES: list[Case] = [
    Case(
        id="path-tilde-expanded",
        stdin=_payload("Read", file_path="~/.aws/credentials"),
        normalise_home=True,
        short_paths=True,
    ),
    Case(
        id="path-relative-resolved-against-cwd",
        stdin=_payload("Read", file_path=".env"),
        normalise_cwd=True,
        short_paths=True,
    ),
    Case(id="path-empty-string", stdin=_payload("Read", file_path="")),
    Case(id="path-key-absent", stdin=_payload("Read")),
    Case(id="write-secret-path", stdin=_payload("Write", file_path="/srv/app/.env")),
    Case(id="edit-secret-path", stdin=_payload("Edit", file_path="/srv/app/.env")),
    Case(
        id="notebookedit-secret-path",
        stdin=_payload("NotebookEdit", notebook_path="/srv/app/secrets/run.ipynb"),
    ),
]

# --- abstention ----------------------------------------------------------- #

ABSTENTION_CASES: list[Case] = [
    _bash("ls -la", case_id="abstain-ordinary-command"),
    _bash("rm -f ./one-file", case_id="abstain-rm-force-without-recursive"),
    _bash("rm -r ./dir", case_id="abstain-rm-recursive-without-force"),
    _bash("git push --force-with-lease origin main", case_id="abstain-force-with-lease"),
    _bash('grep -rn "process\\.env" src/', case_id="abstain-process-env-is-an-api"),
    _bash("", case_id="abstain-empty-command"),
    _read("/srv/app/main.py", case_id="abstain-ordinary-path"),
]

CASES: list[Case] = [
    *SHAPE_CASES,
    *RULE_CASES,
    *ALLOWLIST_CASES,
    *GLOB_CASES,
    *EXCEPTION_CASES,
    *PATH_CASES,
    *ABSTENTION_CASES,
]

#: Every case that must leave all three channels at "no objection".
SILENT_CASE_IDS: frozenset[str] = frozenset(
    c.id
    for c in (
        *SHAPE_CASES,
        *EXCEPTION_CASES,
        *ABSTENTION_CASES,
        Case(id="allowlist-rescues-the-command", stdin=""),
        Case(id="path-empty-string", stdin=""),
        Case(id="path-key-absent", stdin=""),
    )
)


@dataclass(frozen=True)
class Machine:
    """The pinned environment a case runs against."""

    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    home: Path = Path()


def _base_dir(tmp_path: Path, case: Case) -> Iterator[Path]:
    """Where this case's directories live.

    Ordinary cases never put a temp path in the output and use pytest's own.
    A case whose payload resolves against HOME or cwd needs a base short enough
    that the hook's 120-character cut lands on the same character everywhere.
    """
    if not case.short_paths:
        yield tmp_path
        return
    root = short_temp_root()
    if root is None:  # pragma: no cover - both CI platforms are posix
        pytest.skip("no short writable temp root; this golden would not be reproducible")
    base = Path(tempfile.mkdtemp(prefix="lhg", dir=root))
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _machine(tmp_path: Path, case: Case) -> Machine:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    work = tmp_path / "work"
    for d in (home, config_dir, work):
        d.mkdir(parents=True)
    if case.config is not None:
        (config_dir / "config.toml").write_text(case.config)
    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        agent_config_dir=tmp_path / "claude",
    )
    return Machine(cwd=work, env=env, home=home)


def _run(base: Path, case: Case):  # noqa: ANN202 - HookRun, imported for typing only
    machine = _machine(base, case)
    run = run_builtin(MODULE, stdin_text=case.stdin, cwd=machine.cwd, env=machine.env)
    if case.short_paths:
        assert "\u2026" not in run.stderr, (
            "the message was truncated, so the golden would encode this "
            "machine's temp path length rather than the hook's behaviour"
        )
    rules: list[tuple[str, str]] = []
    if case.normalise_home:
        # The hook expands `~` through HOME and echoes the result, so the one
        # variable part of the message is the machine's home directory.
        rules.append((str(machine.home), "<HOME>"))
    if case.normalise_cwd:
        # A relative path is resolved against the process cwd, which is a
        # per-run temporary directory by construction. The child reports the
        # symlink-resolved form (`/private/tmp` on macOS), so both spellings
        # are replaced.
        rules.append((str(machine.cwd.resolve()), "<CWD>"))
        rules.append((str(machine.cwd), "<CWD>"))
    return normalise_run(run, tuple(rules))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    for base in _base_dir(tmp_path, case):
        assert_golden(HOOK, case.id, _run(base, case))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def _refusals_in(case_ids: list[str]) -> set[str]:
    """The `<reason> (<category>)` each golden actually recorded.

    Read back out of the captured bytes rather than off the case table: a case
    whose command matched an earlier rule than the one it was written for would
    otherwise count as covering a rule nothing exercises.
    """
    found: set[str] = set()
    for case_id in case_ids:
        stderr = json.loads(golden_path(HOOK, case_id).read_text())["stderr"]
        head = stderr.splitlines()[0]
        found.add(head.removeprefix("Blocked by lazy-harness PreToolUse: ").rstrip("."))
    return found


def test_every_block_rule_is_exercised_by_a_golden() -> None:
    """A rule added without a golden is a branch the migration can change unseen."""
    from lazy_harness.hooks.builtins.pre_tool_use_security import BLOCK_RULES

    expected = {f"{rule.reason} ({rule.category})" for rule in BLOCK_RULES}

    assert _refusals_in([c.id for c in RULE_CASES]) == expected


def test_every_secret_glob_is_exercised_by_a_golden() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import SECRET_PATH_GLOBS

    expected = {f"Secret path ({glob}) (credentials)" for glob in SECRET_PATH_GLOBS}

    assert _refusals_in([c.id for c in GLOB_CASES]) == expected


def test_every_secret_exception_has_a_golden() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import SECRET_PATH_EXCEPTIONS

    assert len(EXCEPTION_CASES) == len(SECRET_PATH_EXCEPTIONS)


def test_every_inspected_tool_has_a_golden() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import INSPECTED_TOOLS

    covered = {json.loads(c.stdin).get("tool_name") for c in CASES if c.stdin.startswith("{")}
    assert INSPECTED_TOOLS <= covered


@pytest.mark.parametrize("case_id", sorted(SILENT_CASE_IDS))
def test_abstention_emits_nothing_at_all(case_id: str) -> None:
    """The no-objection branch says nothing on any channel.

    A migration that answered with an explicit `allow` would still exit 0 and
    still pass a test that only checked the exit code; the assertion that has
    to hold is that stdout and stderr stay empty.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize(
    "case_id",
    [c.id for c in (*RULE_CASES, *GLOB_CASES)],
)
def test_every_refusal_goes_out_on_stderr_with_exit_2(case_id: str) -> None:
    """Stdout stays empty on a refusal: this hook denies through stderr."""
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 2
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith("Blocked by lazy-harness PreToolUse: ")
