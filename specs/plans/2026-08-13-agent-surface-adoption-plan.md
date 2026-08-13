# Agent Surface Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the dead agent surface that degrades skill routing, and give the two
skills that are wanted-but-never-called a mechanism that actually invokes them.

**Architecture:** Three independent workstreams. Task 1 is a reversible filesystem
operation on both profiles. Task 2 adds one built-in hook to `lazy-harness` following the
existing `post_tool_use_format` pattern — fail-soft, exits 0 on every path. Task 3
produces a written triage of the 49 unused skills across the estate, with no writes to
team repositories.

**Tech Stack:** Python 3.11+, pytest, ruff, `lh` CLI, MkDocs Material.

**Spec:** [`specs/designs/2026-08-13-agent-surface-adoption-design.md`](../designs/2026-08-13-agent-surface-adoption-design.md)

## Global Constraints

- **Worktrees for code.** Task 2 touches `src/` and `tests/`, so it runs in a
  `.worktrees/<short-name>` worktree on a `<type>/<short-name>` branch. Task 1 touches no
  repo file. Task 3 writes only to `specs/analyses/`, which qualifies for the
  documentation short-path.
- **Strict TDD.** No production code without a failing test that exercises it first. No
  exceptions, including hooks.
- **Hooks exit 0 on every path.** The framework does not suppress exceptions; an unhandled
  error escapes to the subprocess and crashes the chain instead of degrading.
- **Adding a built-in hook requires documenting it.** `tests/docs/test_hooks_doc_coherence.py`
  fails if a name in `_BUILTIN_HOOKS` has no `### \`<hook-name>\`` heading under
  "## The built-ins" in `docs/how/hooks.md`. Registration and documentation land in the
  same commit.
- **Registering a hook is not wiring it.** A hook absent from
  `~/.config/lazy-harness/config.toml` under its event's `scripts` list never runs, and
  every test still passes. Wiring plus `lh deploy` plus a verified invocation is the
  definition of done.
- **Pre-commit gate:** `uv run pytest`, `uv run ruff check src tests`, and
  `uv run --group docs mkdocs build --strict` — all three, pristine output.
- **Commits:** `type: short description`. No `Co-Authored-By`, no AI trailers, no
  `--no-verify`.
- **Write boundary:** repositories outside `~/repos/lazy/` belong to FlexibilitySRL.
  Measure and recommend; never commit.

---

### Task 1: Prune the dead global skill cluster

Reversible filesystem work on both profiles. No repo file changes, so no worktree.

**Files:**
- Modify: `~/.claude-lazy/skills/` (remove 36 symlinks)
- Modify: `~/.claude-flex/skills/` (remove 2 stray `.zip` files)
- Untouched: `~/.agents/skills/` (the source tree — nothing is deleted there)

**Interfaces:**
- Consumes: nothing.
- Produces: a reduced skill listing. No code artifact.

- [ ] **Step 1: Record the before state**

```bash
ls -1 ~/.claude-lazy/skills | wc -l   # expect 45
ls -1 ~/.claude-flex/skills | wc -l   # expect 9
ls -1 ~/.claude-lazy/skills > /tmp/skills-lazy-before.txt
ls -1 ~/.claude-flex/skills > /tmp/skills-flex-before.txt
```

- [ ] **Step 2: Verify every target is a symlink, not a real directory**

A real directory here would mean the source lives in the profile and unlinking destroys
it. This check is the difference between reversible and not.

```bash
for d in ~/.claude-lazy/skills/gws-* ~/.claude-lazy/skills/persona-* ~/.claude-lazy/skills/recipe-*; do
  [ -L "$d" ] || echo "NOT A SYMLINK: $d"
done
```

Expected: no output. If any line prints, stop and report — do not continue.

- [ ] **Step 3: Confirm the source tree holds every one of them**

```bash
for d in ~/.claude-lazy/skills/gws-* ~/.claude-lazy/skills/persona-* ~/.claude-lazy/skills/recipe-*; do
  n=$(basename "$d")
  [ -f ~/.agents/skills/"$n"/SKILL.md ] || echo "NO SOURCE: $n"
done
```

Expected: no output. Every skill must exist in `~/.agents/skills/` before its link is cut.

- [ ] **Step 4: Remove the 36 symlinks**

```bash
rm ~/.claude-lazy/skills/gws-* ~/.claude-lazy/skills/persona-* ~/.claude-lazy/skills/recipe-*
ls -1 ~/.claude-lazy/skills | wc -l   # expect 9
```

- [ ] **Step 5: Remove the stray archives from the flex profile**

These are installation residue, not skills — a `.zip` file in `skills/` is never loaded.

```bash
rm ~/.claude-flex/skills/analyzing-ai-workflow-from-git.zip
rm ~/.claude-flex/skills/auditing-ai-harness.zip
ls -1 ~/.claude-flex/skills | wc -l   # expect 7
```

- [ ] **Step 6: Confirm the source tree is intact**

```bash
ls -1 ~/.agents/skills | wc -l   # expect 48 — unchanged
```

- [ ] **Step 7: Verify the effect, not the operation**

A directory listing proves a symlink is gone. It does not prove the model's skill listing
changed — that is the actual deliverable. Open a new session in any project and confirm
no `gws-*`, `persona-*`, or `recipe-*` entry appears in the available-skills list.

Record the observed result. If the entries still appear, the prune did not take effect and
the task is not done.

---

### Task 2: `post-tool-use-ansible-lint` hook

`ansible-lint` and `ansible-security-audit` sit at 0 invocations across 396 sessions in
`lazy-ansible` while the four domain skills there all fire. Nothing calls them. This task
moves linting from "the model must remember" to "the harness executes".

The hook fires on YAML edits inside a repository that has an `ansible.cfg`, so it targets
Ansible repos generally rather than hardcoding one path. It emits results back to the
agent as context — a hook that only writes to a log reproduces the exact defect this
plan exists to fix.

**Files:**
- Create: `src/lazy_harness/hooks/builtins/post_tool_use_ansible_lint.py`
- Create: `tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py`
- Modify: `src/lazy_harness/hooks/loader.py` (add to `_BUILTIN_HOOKS`, ~line 33)
- Modify: `docs/how/hooks.md` (add a `### \`post-tool-use-ansible-lint\`` section)
- Modify: `~/.config/lazy-harness/config.toml` (wire into `[hooks.post_tool_use]`)

**Interfaces:**
- Consumes: `lazy_harness.hooks.builtins._shared.make_log` — signature
  `make_log(prefix: str) -> Callable[[Path, str], None]`, as used by
  `post_tool_use_format._log_unavailable`.
- Produces: `main() -> None`, which always raises `SystemExit(0)`. Module name
  `lazy_harness.hooks.builtins.post_tool_use_ansible_lint`, registry key
  `post-tool-use-ansible-lint`, matcher `Edit|Write`.

- [ ] **Step 1: Create the worktree**

```bash
/new-worktree feat/ansible-lint-hook
```

- [ ] **Step 2: Write the failing test for the happy path**

Create `tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py`:

```python
"""Unit tests for post_tool_use_ansible_lint hook."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _payload(path: str, tool: str = "Edit") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": path}})


def test_runs_ansible_lint_on_yaml_in_ansible_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    role = tmp_path / "roles" / "web" / "tasks"
    role.mkdir(parents=True)
    target = role / "main.yml"
    target.write_text("- name: noop\n")

    fake_run = MagicMock(
        return_value=subprocess.CompletedProcess([], returncode=2, stdout="syntax-check failure", stderr="")
    )
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    args, kwargs = fake_run.call_args
    assert args[0] == ["ansible-lint", str(target)]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 30

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "syntax-check failure" in out["hookSpecificOutput"]["additionalContext"]
```

- [ ] **Step 3: Run it and confirm it fails for the right reason**

```bash
uv run pytest tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.hooks.builtins.post_tool_use_ansible_lint'`.

A failure for any other reason means the test is wrong, not the code.

- [ ] **Step 4: Write the minimal implementation**

Create `src/lazy_harness/hooks/builtins/post_tool_use_ansible_lint.py`:

```python
"""PostToolUse hook — runs `ansible-lint` on YAML edits inside Ansible repos.

Fail-soft: every error path exits 0, because a linter failure must never block
the agent. Results are emitted as additionalContext rather than logged, so the
agent actually sees them. See spec
`specs/designs/2026-08-13-agent-surface-adoption-design.md`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ANSIBLE_LINT_TIMEOUT_SECS = 30
MAX_CONTEXT_CHARS = 4000


def _read_stdin_json() -> dict[str, Any]:
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


def _find_ansible_root(path: Path) -> Path | None:
    """Walk up looking for ansible.cfg. None means this is not an Ansible repo."""
    for parent in [path, *path.parents]:
        if (parent / "ansible.cfg").is_file():
            return parent
    return None


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    raw = str(payload.get("tool_input", {}).get("file_path", ""))
    if not raw.endswith((".yml", ".yaml")):
        sys.exit(0)

    path = Path(raw)
    if _find_ansible_root(path) is None:
        sys.exit(0)

    try:
        result = subprocess.run(
            ["ansible-lint", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=ANSIBLE_LINT_TIMEOUT_SECS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        _log_unavailable(str(path), e)
        sys.exit(0)

    if result.returncode == 0:
        sys.exit(0)

    body = (result.stdout or result.stderr or "").strip()[:MAX_CONTEXT_CHARS]
    if body:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"ansible-lint on {path.name}:\n{body}",
                    }
                }
            )
        )
    sys.exit(0)


def _log_unavailable(path: str, error: Exception) -> None:
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.paths import agent_runtime_dir
        from lazy_harness.hooks.builtins._shared import make_log

        agent_dir = agent_runtime_dir(get_agent("claude-code"))
        log = make_log("post-tool-use-ansible-lint")
        log(
            agent_dir / "logs" / "hooks.log",
            f"ansible-lint unavailable ({type(error).__name__}), left {path} unchecked",
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
uv run pytest tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py -v
```

Expected: PASS.

- [ ] **Step 6: Write the failing tests for every skip and failure path**

Each of these is a path where a silently-wrong hook looks identical to a correct one.

Append to the same test file:

```python
def test_skips_non_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("/abs/foo.py")))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_skips_yaml_outside_ansible_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    target = tmp_path / "docker-compose.yml"
    target.write_text("services: {}\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_emits_nothing_when_lint_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(return_value=subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_exits_zero_when_ansible_lint_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The binary being absent must degrade, not crash the hook chain."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError))
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0


def test_exits_zero_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="ansible-lint", timeout=30)),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0


def test_exits_zero_on_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
```

- [ ] **Step 7: Run the full hook test file**

```bash
uv run pytest tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py -v
```

Expected: 7 passed. All of these should already pass against the Step 4 implementation —
they pin behaviour that exists rather than driving new code. If any fails, the
implementation is wrong; fix it before continuing.

- [ ] **Step 8: Commit the hook and its tests**

```bash
git add src/lazy_harness/hooks/builtins/post_tool_use_ansible_lint.py \
        tests/unit/hooks/builtins/test_post_tool_use_ansible_lint.py
git commit -m "feat: add post-tool-use-ansible-lint hook"
```

- [ ] **Step 9: Write the failing test for registry registration**

Add to `tests/unit/test_hook_loader.py`:

```python
def test_ansible_lint_hook_is_registered_with_edit_write_matcher() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hook

    assert "post-tool-use-ansible-lint" in list_builtin_hooks()
    info = resolve_hook("post-tool-use-ansible-lint")
    assert info is not None
    assert info.is_builtin is True
    assert info.matcher == "Edit|Write"
```

`resolve_hook` is the public lookup (`src/lazy_harness/hooks/loader.py:90`); `_find_builtin`
is private and must not be called from tests. Existing tests in this file already import
`resolve_hook` the same way.

- [ ] **Step 10: Run it and confirm it fails**

```bash
uv run pytest tests/unit/test_hook_loader.py -k ansible_lint -v
```

Expected: FAIL — the key is not in `_BUILTIN_HOOKS`.

- [ ] **Step 11: Register the hook**

In `src/lazy_harness/hooks/loader.py`, add to `_BUILTIN_HOOKS` in alphabetical position
(after `"post-tool-use-format"`):

```python
    "post-tool-use-ansible-lint": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.post_tool_use_ansible_lint",
        matcher="Edit|Write",
    ),
```

- [ ] **Step 12: Run the loader test and the doc coherence test**

```bash
uv run pytest tests/unit/test_hook_loader.py -k ansible_lint -v
uv run pytest tests/docs/test_hooks_doc_coherence.py -v
```

Expected: the loader test PASSES, and the doc coherence test now FAILS with
`post-tool-use-ansible-lint` listed as registered-but-not-documented. That failure is
correct — it is the guard doing its job.

- [ ] **Step 13: Document the hook**

In `docs/how/hooks.md`, under `## The built-ins`, add a section matching the existing
heading shape exactly — the coherence test parses `^### \`([a-z0-9-]+)\``:

```markdown
### `post-tool-use-ansible-lint` — runs on `PostToolUse`

Runs `ansible-lint` after any `Edit` or `Write` to a `.yml` or `.yaml` file that sits
inside a repository containing an `ansible.cfg`.

Findings are returned to the agent as additional context rather than written to a log, so
a lint failure is visible in the session that caused it. Clean runs emit nothing.

The hook is fail-soft: a missing `ansible-lint` binary, a timeout, or malformed input all
exit 0 and leave the file unchecked. A note is written to `logs/hooks.log` when the binary
is unavailable, so a linter that never ran is distinguishable from one that always passed.
```

- [ ] **Step 14: Run the full gate**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
```

Expected: all three pass with pristine output.

- [ ] **Step 15: Commit registration and docs together**

```bash
git add src/lazy_harness/hooks/loader.py tests/unit/test_hook_loader.py docs/how/hooks.md
git commit -m "feat: register and document post-tool-use-ansible-lint hook"
```

- [ ] **Step 16: Open the PR and merge**

```bash
gh auth switch --hostname github.com --user lazynet
git push -u origin feat/ansible-lint-hook
gh pr create --title "feat: add post-tool-use-ansible-lint hook" \
  --body "Implements W2 of specs/designs/2026-08-13-agent-surface-adoption-design.md"
```

The account switch matters: `mvago-flx` is the default active account and pushing as it
leaks a work identity into a personal public repo. Switch back with
`gh auth switch --hostname github.com --user mvago-flx` after the PR is open.

- [ ] **Step 17: Wire the hook — registration alone does nothing**

After the PR merges, add the hook to the `post_tool_use` scripts list in
`~/.config/lazy-harness/config.toml`:

```toml
[hooks.post_tool_use]
scripts = ["post-tool-use-format", "post-tool-use-sync-claude", "post-tool-use-ansible-lint"]
```

Then deploy:

```bash
lh deploy
```

- [ ] **Step 18: Verify the hook actually fires**

`lh deploy` exiting 0 is not proof the hook runs. Confirm the generated agent config
contains it, then trigger it for real:

```bash
grep -c "post_tool_use_ansible_lint" ~/.claude/settings.json   # expect >= 1
```

In a session inside `~/repos/lazy/lazy-ansible`, edit any file under `roles/` and confirm
the lint output appears in context. Record the observed result.

If nothing appears, check `~/.claude/logs/hooks.log` for the unavailable-binary note
before assuming the hook is broken — `ansible-lint` may simply not be installed.

---

### Task 3: Estate-wide triage report

Turns the 49 unused skills into a bucketed, actionable record. No code, no writes outside
`lazy-harness`.

**Files:**
- Create: `specs/analyses/2026-08-13-unused-skill-triage.md`
- Read-only: every repo listed in `specs/analyses/2026-08-13-agent-surface-audit.txt`

**Interfaces:**
- Consumes: `specs/analyses/2026-08-13-agent-surface-audit.txt` (the audit output, already
  committed) — columns `REPO SKILLS MCPs SESSIONS INVOCS UNUSED_SKILLS`.
- Produces: a markdown report. No code artifact.

- [ ] **Step 1: Re-run the audit to get current numbers**

```bash
bash specs/analyses/2026-08-13-agent-surface-audit.sh > /tmp/audit-current.txt
diff specs/analyses/2026-08-13-agent-surface-audit.txt /tmp/audit-current.txt || true
```

Session counts drift as work continues; that is expected. A change in the `UNUSED_SKILLS`
column is not — investigate any skill that moved in or out of that list.

- [ ] **Step 2: Assign every unused skill to a bucket**

For each name in the `UNUSED_SKILLS` column, assign exactly one of:

1. **Superseded** — a competing surface already does this job, with invocation counts to
   prove it. Verify by measuring the competitor, not by assuming:
   ```bash
   grep -rho '"command":"[^"]*gws [a-z]*' ~/.claude-flex/projects --include="*.jsonl" | wc -l
   ```
2. **Repo never opened** — the repo's `SESSIONS` column is 0. No verdict is possible.
3. **Sample too small** — `SESSIONS` under 20. No verdict is possible.
4. **Wanted but untriggered** — the work happens by hand, or sibling stages of the same
   flow fire while this one does not.

- [ ] **Step 3: For bucket 4 only, test the description-mismatch hypothesis**

Read the skill's `description:` frontmatter, then read the opening user prompt of several
sessions in that repo:

```bash
grep -m1 '^description:' <repo>/.claude/skills/<name>/SKILL.md
```

A skill whose description names the artifact ("Iceberg table best practices") while
prompts name the task ("why is this job failing") will never match. Record whether the
overlap is present or absent — that determines whether the fix is a reworded description
or a hook.

- [ ] **Step 4: Write the report**

Create `specs/analyses/2026-08-13-unused-skill-triage.md` with one row per unused skill:
repo, skill, bucket, evidence, recommendation. Buckets 2 and 3 get "no verdict" plus the
reason — recording why a conclusion is unavailable is the deliverable there, not a gap.

State explicitly which repos are FlexibilitySRL-owned and therefore recommendation-only.

- [ ] **Step 5: Commit via the documentation short-path**

`specs/analyses/**` is inside the short-path allowlist, so this goes directly to `main`
with a `docs(...)` commit type. No worktree, no PR.

```bash
git add specs/analyses/2026-08-13-unused-skill-triage.md
git commit -m "docs(specs): triage the 49 unused skills across the estate"
gh auth switch --hostname github.com --user lazynet
git push origin main
gh auth switch --hostname github.com --user mvago-flx
```

---

## Deferred: graphify

The spec's W4 proposed a `SessionStart` hook to surface graph freshness. **That mechanism
already exists and is already running** — `graphify_section()` in
`src/lazy_harness/hooks/builtins/context_inject.py:544` detects `graphify-out/graph.json`,
compares its mtime against HEAD, and injects a staleness banner.
`graphify_surface_enabled` is `true` in the active config, and the section was injected in
70 recorded sessions.

The MCP still recorded 0 calls. Context injection did not produce adoption, so building
another trigger would repeat a mechanism that has already been measured as insufficient.
No task in this plan implements W4; the decision is open and belongs to the user.
