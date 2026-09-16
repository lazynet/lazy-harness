"""Byte goldens for `post-tool-use-ansible-lint`, captured before its migration.

This is the one hook in wave D whose output channel a golden can see:
`additionalContext` on stdout. The other two write on no channel at all, so
every case of theirs freezes to the same empty triple and a `main()` whose body
is `return HookDecision()` reproduces all of them. Here the cases discriminate,
because the hook's whole job is putting lint findings in front of the agent.

**The binary is planted, not mocked and not required.** `pinned_env` gives the
child a PATH holding git and nothing else, so `ansible-lint` is absent on every
machine by construction — which makes the *unavailable* branch deterministic and
the other branches unreachable. The repo's own gate says why a third option is
out: "a bare command name resolves from ambient `PATH`", so a case that ran the
real `ansible-lint` would freeze the capturing machine's version, its rule set
and its `.ansible-lint` discovery into the golden, and a case that skipped when
the binary was missing would cover nothing on CI. So the cases that need a
verdict put a `/bin/sh` script named `ansible-lint` on the pinned PATH and pick
its three channels. `monkeypatch` cannot reach across the process boundary these
goldens exist to cross; the in-process unit tests next door patch
`subprocess.run` instead, which is the right tool on their side of it.

**`cwd` is not a variable here, unlike every other hook in the plan.** Trap 1 is
about builtins that encode the working directory into a path they write; this
one never reads `cwd` at all, before or after the migration. The directory it
passes to `subprocess.run` is the Ansible root it discovered by walking up from
the edited file. The cases still declare `cwd`, because a payload without one is
not the shape the agent sends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    pinned_env,
    run_through_runner,
)

HOOK = "post-tool-use-ansible-lint"

SESSION = "0193b0de-1111-2222-3333-444455556666"

_CONFIG_MIN = '[harness]\nversion = "1"\n'

#: What the planted `ansible-lint` prints on the branch that has a finding.
#: A literal with no quote characters: the shim embeds it in a `printf '%s'`
#: argument, and it must survive that without escaping.
_FINDING = (
    "roles/web/tasks/main.yml:2: syntax-check[unknown-module] "
    "couldnt resolve module/action mynamespace.mycollection.mymodule\n"
    "Read documentation for the rule: fqcn"
)

#: The same shape on the other channel. `main` prefers stdout and falls back to
#: stderr, and only a case where stdout is empty proves the fallback is live.
_FINDING_ON_STDERR = "WARNING  Listing 1 violation(s) that are fatal\nload-failure: couldnt parse"

#: Longer than `MAX_CONTEXT_CHARS`, so the cut is in the golden's bytes.
_LONG_FINDING = "\n".join(
    f"roles/web/tasks/main.yml:{n}: name[casing] line {n}" for n in range(200)
)


@dataclass(frozen=True)
class Case:
    """One branch of the hook's decision."""

    id: str
    #: Relative to the Ansible root the fixture builds, or to `work` when
    #: `ansible_cfg` is False.
    target: str
    #: Body written to the target before the hook runs.
    target_body: str = "- name: noop\n"
    #: Put an `ansible.cfg` at the root, making it an Ansible repo at all.
    ansible_cfg: bool = True
    #: Plant an `ansible-lint` on PATH. `None` leaves the binary missing, which
    #: is `pinned_env`'s natural state and the unavailable branch's input.
    lint_exit: int | None = None
    lint_stdout: str = ""
    lint_stderr: str = ""
    #: The tool the payload names. `NotebookEdit` is trap 3's input.
    tool_name: str = "Edit"
    #: The payload key carrying the path. Claude Code uses `notebook_path` for
    #: `NotebookEdit` and `file_path` for everything else.
    path_key: str = "file_path"
    #: Send no path at all, for the shape a malformed `tool_input` produces.
    omit_path: bool = False
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


CASES: list[Case] = [
    # The branch the hook exists for: a finding reaches the agent.
    Case(
        id="finding-is-fed-back-as-context",
        target="roles/web/tasks/main.yml",
        lint_exit=2,
        lint_stdout=_FINDING,
    ),
    # stdout empty, stderr carrying the finding: `main`'s `or` fallback.
    Case(
        id="finding-arrives-on-stderr-only",
        target="playbooks/site.yml",
        lint_exit=2,
        lint_stderr=_FINDING_ON_STDERR,
    ),
    # `MAX_CONTEXT_CHARS` is a promise about how much of the transcript this
    # hook is allowed to spend. A golden is the only place the cut is visible.
    Case(
        id="a-long-finding-is-truncated",
        target="roles/web/tasks/main.yml",
        lint_exit=2,
        lint_stdout=_LONG_FINDING,
    ),
    # Clean file: the hook is silent. Distinguishable from the skips below only
    # because the shim records that it ran -- see `test_a_clean_run_still_linted`.
    Case(id="clean-file-emits-nothing", target="site.yaml", lint_exit=0),
    # Non-zero with nothing to say: logged, not surfaced. Surfacing an empty
    # body would put a bare header in the transcript with no finding under it.
    Case(id="nonzero-exit-with-no-output-is-only-logged", target="site.yaml", lint_exit=7),
    # The binary is absent -- the default state of `pinned_env`'s PATH, and the
    # state of any machine that has not installed ansible-lint. The hook says so
    # on the channel rather than only in a log the agent never reads.
    Case(id="binary-unavailable-is-reported-to-the-agent", target="site.yaml"),
    # --- the skips, each reached by a different guard --------------------
    Case(id="non-yaml-suffix-is-skipped", target="roles/web/tasks/main.py", lint_exit=2),
    Case(
        id="yaml-outside-an-ansible-repo-is-skipped",
        target="docker-compose.yml",
        ansible_cfg=False,
        lint_exit=2,
    ),
    Case(
        id="yaml-outside-lint-scope-is-skipped",
        target="docker/traefik/dynamic.yml",
        lint_exit=2,
    ),
    Case(
        id="vault-encrypted-yaml-is-skipped",
        target="roles/web/vars/vault.yml",
        target_body="$ANSIBLE_VAULT;1.1;AES256\n66386439653236336462626566\n",
        lint_exit=2,
    ),
    # Trap 3, frozen as bytes. `_TOOL_OPERATIONS` maps `NotebookEdit` to
    # `MODIFY_FILE` beside `Edit` and `Write`, and `_FILE_PATH_KEYS` reads
    # `notebook_path`, so a notebook whose path ends `.yml` clears the suffix
    # re-check. Nothing in `ToolCall` makes a notebook path end `.ipynb`. This
    # case is what turns red if the tool-name gate is replaced by the operation.
    Case(
        id="notebook-edit-naming-a-yaml-path-is-not-inspected",
        target="roles/web/tasks/main.yml",
        tool_name="NotebookEdit",
        path_key="notebook_path",
        lint_exit=2,
    ),
    Case(id="a-tool-input-naming-no-path-is-skipped", target="site.yaml", omit_path=True),
    Case(id="stdin-empty", target="site.yaml", raw_stdin=""),
    Case(id="stdin-malformed-json", target="site.yaml", raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration `_read_stdin_json` degraded them to `{}`, the tool-name gate saw
#: nothing and the hook exited 0 silently -- so these two are the licensed
#: divergence, and the only two.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})


@dataclass
class World:
    """The tmp tree one case runs in."""

    work: Path
    root: Path
    target: Path
    agent_dir: Path
    global_agent_dir: Path
    lint_marker: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"


def _plant_lint(directory: Path, marker: Path, case: Case) -> None:
    """A `/bin/sh` stand-in for `ansible-lint`, on the pinned PATH.

    `printf` and `[` are shell builtins and `/bin/sh` is an absolute path, so
    the script runs under a PATH that reaches no other binary -- which is what
    `pinned_env` hands it. The marker file is how a test tells "the hook ran the
    linter and it was clean" apart from "the hook never ran the linter", two
    states that write identical bytes on every channel.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["#!/bin/sh", f"printf x >> {marker}"]
    if case.lint_stdout:
        lines.append(f"printf '%s' '{case.lint_stdout}'")
    if case.lint_stderr:
        lines.append(f"printf '%s' '{case.lint_stderr}' >&2")
    lines.append(f"exit {case.lint_exit}")
    script = directory / "ansible-lint"
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**: `agent_runtime_dir` resolves the adapter's env var
    above the profile's `config_dir`, so leaving it set makes the global answer
    and the per-profile answer the same path and no isolation assertion can fail.
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

    if case.ansible_cfg:
        (work / "ansible.cfg").write_text("[defaults]\n")
    target = work / case.target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(case.target_body)

    marker = tmp_path / "lint-invocations"
    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
    )
    if case.lint_exit is not None:
        bin_dir = tmp_path / "bin"
        _plant_lint(bin_dir, marker, case)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        tool_input: dict[str, object] = {}
        if not case.omit_path:
            tool_input[case.path_key] = str(target)
        stdin = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": SESSION,
                "cwd": str(work),
                "tool_name": case.tool_name,
                "tool_input": tool_input,
            }
        )

    return World(
        work=work,
        root=work,
        target=target,
        agent_dir=agent_dir,
        global_agent_dir=global_agent_dir,
        lint_marker=marker,
        env=env,
        stdin=stdin,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert_golden(HOOK, case.id, run)


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_no_golden_leaks_a_path_from_the_machine_that_captured_it() -> None:
    """Every case's bytes are reproducible off this repo alone.

    `main` puts `path.name` on the channel rather than the path, which is what
    makes that true; a change to the full path would show up here rather than
    as a golden that only reproduces on one machine.
    """
    for case in CASES:
        golden = json.loads(golden_path(HOOK, case.id).read_text())
        blob = golden["stdout"] + golden["stderr"]
        assert "/Users/" not in blob, case.id
        assert "/private/" not in blob, case.id
        assert "/tmp/" not in blob, case.id


def test_the_finding_reaches_the_agent_on_the_context_channel() -> None:
    """The bytes the agent actually reads, named rather than left in a file.

    A hook that started logging its findings instead of returning them would
    keep exit code 0 and an empty stdout, which reads as a clean file.
    """
    golden = json.loads(golden_path(HOOK, "finding-is-fed-back-as-context").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]

    assert golden["exit_code"] == 0
    assert body["hookEventName"] == "PostToolUse"
    assert body["additionalContext"] == f"ansible-lint on main.yml:\n{_FINDING}"


def test_a_finding_on_stderr_alone_still_reaches_the_agent() -> None:
    """`main` reads `result.stdout or result.stderr`, and only this case proves it."""
    golden = json.loads(golden_path(HOOK, "finding-arrives-on-stderr-only").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]

    assert body == f"ansible-lint on site.yml:\n{_FINDING_ON_STDERR}"


def test_a_long_finding_is_cut_at_the_declared_budget() -> None:
    """`MAX_CONTEXT_CHARS` bounds what one lint run costs the transcript."""
    from lazy_harness.hooks.builtins.post_tool_use_ansible_lint import MAX_CONTEXT_CHARS

    golden = json.loads(golden_path(HOOK, "a-long-finding-is-truncated").read_text())
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]
    header, _, finding = body.partition("\n")

    assert header == "ansible-lint on main.yml:"
    assert len(finding) == MAX_CONTEXT_CHARS
    assert finding == _LONG_FINDING.strip()[:MAX_CONTEXT_CHARS]


def test_a_missing_binary_is_reported_rather_than_swallowed() -> None:
    """The state of any machine that has not installed ansible-lint.

    Silence here is worse than noise: the agent would read a clean lint from a
    hook that never ran one. The wording is frozen because it is the only thing
    that tells the two apart.
    """
    golden = json.loads(
        golden_path(HOOK, "binary-unavailable-is-reported-to-the-agent").read_text()
    )
    body = json.loads(golden["stdout"])["hookSpecificOutput"]["additionalContext"]

    assert golden["exit_code"] == 0
    assert body == (
        "ansible-lint is unavailable (FileNotFoundError); site.yaml was left unchecked."
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "clean-file-emits-nothing",
        "nonzero-exit-with-no-output-is-only-logged",
        "non-yaml-suffix-is-skipped",
        "yaml-outside-an-ansible-repo-is-skipped",
        "yaml-outside-lint-scope-is-skipped",
        "vault-encrypted-yaml-is-skipped",
        "notebook-edit-naming-a-yaml-path-is-not-inspected",
        "a-tool-input-naming-no-path-is-skipped",
    ],
)
def test_the_silent_branches_write_nothing_on_any_channel(case_id: str) -> None:
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_a_clean_run_still_linted(tmp_path: Path) -> None:
    """The one thing the silent goldens cannot say, said here instead.

    `clean-file-emits-nothing` and the six skips freeze to identical bytes, so
    the golden alone cannot tell "linted and found nothing" from "never linted".
    The planted binary appends to a marker file; this is the case where it must
    have run, and `test_the_skips_never_invoke_the_linter` is the contrast.
    """
    case = next(c for c in CASES if c.id == "clean-file-emits-nothing")
    world = _build(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert run.exit_code == 0, run.stderr
    assert world.lint_marker.read_text() == "x"


@pytest.mark.parametrize(
    "case_id",
    [
        "non-yaml-suffix-is-skipped",
        "yaml-outside-an-ansible-repo-is-skipped",
        "yaml-outside-lint-scope-is-skipped",
        "vault-encrypted-yaml-is-skipped",
        "notebook-edit-naming-a-yaml-path-is-not-inspected",
    ],
)
def test_the_skips_never_invoke_the_linter(case_id: str, tmp_path: Path) -> None:
    """Each guard is a refusal to spend a subprocess, not just a silent return.

    Without this, every one of these cases passes against a hook that ran
    `ansible-lint` on a Traefik config, a vault ciphertext or a notebook and
    happened to discard the result.
    """
    case = next(c for c in CASES if c.id == case_id)
    world = _build(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert run.exit_code == 0, run.stderr
    assert not world.lint_marker.exists(), world.lint_marker.read_text()


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The only two goldens this migration did not keep byte-identical, named.

    Twelve of the fourteen cases matched their pre-migration capture exactly.
    These two are decision 3's informational column: the runner refuses a
    payload it cannot parse *before* the builtin is reached, where
    `_read_stdin_json` used to degrade it to `{}` and let the tool-name gate
    exit 0 on it. What the pre-migration bytes carried, recorded here because
    the files no longer do:

        {"exit_code": 0, "stderr": "", "stdout": ""}

    Nothing is lost: on `{}` this hook had no tool call, no path and no file to
    lint, so the refusal replaces a silent no-op with a named one.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")
