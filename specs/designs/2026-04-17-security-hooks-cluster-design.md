# Security hooks cluster — design

**Date:** 2026-04-17
**Status:** proposed
**Related ADRs:** [`006-hooks-subprocess-json.md`](../adrs/006-hooks-subprocess-json.md), [`009-profile-symlink-deploy.md`](../adrs/009-profile-symlink-deploy.md)
**Backlog items:** `PreToolUse security` + `PostToolUse auto-format` (Prioridad ALTA cluster in [`specs/backlog.md`](../backlog.md))

## Goal

Close two harness gaps that hooks today do not cover:

1. **Destructive / exfiltration commands pass without control** — `rm -rf`, `terraform destroy`, `git push --force`, reads of `.env` / SSH keys / AWS creds, forced `git add` of secrets. The profile isolation from ADR-009 only prevents *cross-profile* damage; inside a profile anything goes.
2. **Formatting depends on agent memory** — every `Edit` or `Write` to a `.py` file today relies on the agent remembering to run `ruff format`. That is not a guarantee, it is hope. The `/tdd-check` gate catches it post-facto but the ruff failures are noise in the commit cycle.

Both gaps are closed by two new builtin hooks that Claude Code invokes automatically. They ship as a single cluster (one PR, two hooks) because they share surface: the hook builtin directory, the `config.toml` generator, the `settings.json` deploy path, and the test infrastructure.

## Non-goals

- Blocking `echo $SECRET` / `printf $TOKEN` style exfiltration. False-positive rate is too high (`echo $USER`, `echo $PATH`, legitimate CI scripts) and would require per-variable allowlists. Deferred to a v2 if evidence of actual exfiltration appears.
- Multi-formatter support (JSON, YAML, Markdown). The backlog identifies Python-format drift only; widening scope to other languages has no evidence of pain.
- `ruff check --fix --unsafe-fixes` as part of the PostToolUse hook. Unsafe fixes can change semantics silently (a comprehension simplification that shifts behavior) and the agent would not see the diff. `ruff format` is idempotent and whitespace-only.
- Interactive confirmation. Hooks are non-interactive by contract (ADR-006). If a command is blocked, the agent either rewords it or the human adds the pattern to the allowlist.

## Architecture

Two Python modules under `src/lazy_harness/hooks/builtins/`, following the same shape as the existing builtins (`pre_compact.py`, `session_end.py`):

```
src/lazy_harness/hooks/builtins/
├── pre_tool_use_security.py    [NEW]
├── post_tool_use_format.py     [NEW]
├── pre_compact.py              (existing)
├── session_end.py              (existing)
└── ...
```

Registered in the builtin dispatcher `src/lazy_harness/hooks/loader.py:_BUILTIN_HOOKS`:

```python
_BUILTIN_HOOKS = {
    ...,
    "pre-tool-use-security": "lazy_harness.hooks.builtins.pre_tool_use_security",
    "post-tool-use-format":  "lazy_harness.hooks.builtins.post_tool_use_format",
}
```

### Profile config shape

Each profile's `config.toml` gains two blocks:

```toml
[hooks.pre_tool_use]
scripts = ["pre-tool-use-security"]
allow_patterns = [
  # Regex patterns that exempt a matched command from blocking.
  # Example: "\\brm\\s+-rf\\s+\\.worktrees/" — cleanup-worktree scripts
]

[hooks.post_tool_use]
scripts = ["post-tool-use-format"]
```

Both blocks are added **default-on** to the `lh init` template so future profiles inherit them automatically. Existing profiles (`lazy` and `flex`) need a one-time manual snippet paste documented in the PR description — avoids building a migration command for a two-profile user base.

### Claude Code settings.json emission

`src/lazy_harness/agents/claude_code.py` already translates the internal `hook_event_map` to native Claude Code events. The two new entries emit:

```json
{
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "python -m lazy_harness.hooks.builtins.pre_tool_use_security"}]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [{"type": "command", "command": "python -m lazy_harness.hooks.builtins.post_tool_use_format"}]
    }
  ]
}
```

- **PreToolUse matcher `Bash`**: only shell commands are the blast radius; `Read`, `Grep`, `Glob` do not mutate state or exfiltrate via logs in a way the patterns target.
- **PostToolUse matcher `Edit|Write`**: regex OR, matches both tools. Excludes `NotebookEdit` (rarely used, no ruff support for notebooks).

### Contract divergence from ADR-006

ADR-006 specifies "exit 0 always, JSON stdin/stdout" as the hook contract. The PostToolUse hook follows this unchanged. **The PreToolUse hook deliberately deviates**: Claude Code's PreToolUse semantics are that `exit 2` with stderr output is interpreted as a **block** decision, and the stderr content is surfaced back to the agent. This deviation is intentional and will be noted as an addendum to ADR-006 in the implementation PR (or as a dedicated ADR if the review surfaces further PreToolUse hooks coming).

## Components

### `pre_tool_use_security.py`

**Data model (hardcoded in-module):**

```python
from dataclasses import dataclass
from typing import Literal
import re

Category = Literal["filesystem", "sql", "terraform", "credentials", "git"]


@dataclass(frozen=True)
class BlockRule:
    category: Category
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class BlockDecision:
    rule: BlockRule
    matched_text: str


BLOCK_RULES: tuple[BlockRule, ...] = (
    BlockRule("filesystem",  re.compile(r"\brm\s+-[rRf]*[rRf][rRf]*\b.+"),                                            "Recursive delete"),
    BlockRule("filesystem",  re.compile(r"\btruncate\s+(-s\s+\d+\s+)?[^\s-]"),                                        "File truncation"),
    BlockRule("git",         re.compile(r"\bgit\s+push\s+(--force\b|-f\b)(?!.*--force-with-lease)"),                  "Force-push without lease"),
    BlockRule("git",         re.compile(r"\bgit\s+reset\s+--hard\b"),                                                 "Hard reset discards work"),
    BlockRule("git",         re.compile(r"\bgit\s+add\s+(-f\b|--force\b)[^|;&]*(\.env|\.pem|\.key|\.p12|credentials|id_rsa|id_ed25519)"), "Forced add of secret"),
    BlockRule("sql",         re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.IGNORECASE),                    "SQL destruction"),
    BlockRule("terraform",   re.compile(r"\bterraform\s+destroy\b"),                                                  "Infra destruction"),
    BlockRule("terraform",   re.compile(r"\bterraform\s+apply\s+[^|;&]*-auto-approve\b"),                             "Skips plan review"),
    BlockRule("terraform",   re.compile(r"\bterraform\s+apply\s+[^|;&]*-replace=\S+"),                                "Forces resource recreation"),
    BlockRule("terraform",   re.compile(r"\bterraform\s+state\s+(rm|push)\b"),                                        "State mutation"),
    BlockRule("credentials", re.compile(r"\b(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&]*\.env\b(?!\.(example|sample|template))"), "Read of .env"),
    BlockRule("credentials", re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.ssh/id_\S+"),                     "Read of SSH private key"),
    BlockRule("credentials", re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.aws/(credentials|config)\b"),     "Read of AWS credentials"),
    BlockRule("credentials", re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.(pem|key|p12)\b"),                "Read of cert/key file"),
)
```

Pattern authoring notes:

- The `[^|;&]*` guard prevents matches where the credentials path is on the *right* side of a pipe / semicolon / ampersand (i.e., legitimate commands that only reference a sensitive path as a pipe sink, such as `some-generator | tee out.pem`). The intent is to catch direct *reads*, not all mentions.
- `(?!--force-with-lease)` negative-lookahead on `git push --force` allows the safer lease variant through.
- `re.IGNORECASE` only on the SQL patterns — SQL is case-insensitive by convention; the rest are shell tokens that are case-sensitive.

**Pure logic:**

```python
def should_block(command: str, allow_patterns: list[str]) -> BlockDecision | None:
    """Return a BlockDecision if command matches a rule and no allow_pattern rescues it."""
    for rule in BLOCK_RULES:
        match = rule.pattern.search(command)
        if match is None:
            continue
        if any(_safe_search(ap, command) for ap in allow_patterns):
            return None  # Rescued by user allowlist.
        return BlockDecision(rule=rule, matched_text=match.group(0))
    return None


def _safe_search(pattern: str, text: str) -> bool:
    """Compile-and-search; broken user regexes are logged and skipped, never raised."""
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False
```

**Entry point:**

```python
def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = payload.get("tool_input", {}).get("command", "")
    allow = _load_allowlist()
    decision = should_block(command, allow)
    if decision is None:
        sys.exit(0)
    sys.stderr.write(_format_block_message(decision))
    sys.exit(2)
```

**Block message format** (stderr, consumed by Claude Code and surfaced to the agent):

```
Blocked by lazy-harness PreToolUse: <reason> (<category>).
Matched: <truncated matched_text, max 120 chars>
If this is intentional, add a regex pattern to [hooks.pre_tool_use] allow_patterns in your profile config.toml.
See specs/designs/2026-04-17-security-hooks-cluster-design.md for the full rule list.
```

**Allowlist loading** (`_load_allowlist()`):

1. Locate the profile's `config.toml` by consulting `$CLAUDE_CONFIG_DIR` (set by the `lcc` wrapper per ADR-009) and walking up to the harness config root.
2. Parse `[hooks.pre_tool_use].allow_patterns` as `list[str]`.
3. On any failure (missing file, malformed TOML, missing section) return `[]`. This is fail-safe: no allowlist → stricter blocking, not looser.

### `post_tool_use_format.py`

```python
def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    path = payload.get("tool_input", {}).get("file_path", "")
    if not path.endswith(".py"):
        sys.exit(0)
    # Fail-soft: ruff format errors must not block the agent.
    # `ruff` is expected to be on PATH (installed via `uv tool install ruff`).
    # If missing, FileNotFoundError is caught below and the hook no-ops.
    try:
        subprocess.run(
            ["ruff", "format", path],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    sys.exit(0)
```

**Why `ruff format` plain and not `uv run ruff format`:** the hook runs with the CWD of wherever Claude Code is invoked, which is not necessarily the `lazy-harness` repo. `uv run` requires a `pyproject.toml` with `ruff` as a dep in the current working tree; if the agent is editing Python files in any other project, `uv run` would either fail noisily or sync an unrelated venv. A globally-installed `ruff` (via `uv tool install ruff`) works uniformly across every CWD and respects whatever `pyproject.toml`-local `[tool.ruff]` config exists in the target file's repo, which is the correct semantic.

This makes `ruff` on the global PATH a prerequisite, documented in the install instructions and detected by `lh doctor` (see delivery plan).

## Data flow

**PreToolUse path:**

1. Claude Code emits `{"tool_name": "Bash", "tool_input": {"command": "..."}}` on the hook's stdin.
2. Non-Bash tool calls → `sys.exit(0)` silently.
3. Allowlist loaded from the profile `config.toml` (empty list if unreachable).
4. `should_block(command, allowlist)` walks `BLOCK_RULES` top-to-bottom; **first match wins**, even if a later rule is more specific.
5. Block: formatted message to stderr + `sys.exit(2)`. No match: silent `sys.exit(0)`.

**PostToolUse path:**

1. Claude Code emits `{"tool_name": "Edit" | "Write", "tool_input": {"file_path": "..."}}`.
2. Non-Edit/Write or non-`.py` → `sys.exit(0)` silently.
3. `ruff format <path>` via `uv run`, with `check=False` (errors do not raise).
4. `sys.exit(0)` always.

## Error handling

| Failure mode                               | PreToolUse behavior                               | PostToolUse behavior       |
|--------------------------------------------|---------------------------------------------------|----------------------------|
| Malformed stdin JSON                       | `sys.exit(0)` (fail-open; Claude Code's bug)      | `sys.exit(0)`              |
| `config.toml` missing / unreadable         | Empty allowlist → stricter blocking (fail-safe)   | N/A                        |
| Regex compile error in code                | Caught at import-time by tests                    | N/A                        |
| Invalid regex in user's `allow_patterns`   | Log to `hooks.log`, skip that entry, continue     | N/A                        |
| `ruff` not found on PATH                   | N/A                                               | Catch `FileNotFoundError`, log, exit 0 |
| `ruff format` subprocess returns non-zero  | N/A                                               | Log stderr to `hooks.log`, exit 0 |
| `ruff format` exceeds 10s timeout          | N/A                                               | Catch `TimeoutExpired`, log, exit 0 |
| Path does not exist at format time         | N/A                                               | `ruff format` reports error, exit 0 |

All logging goes to `$CLAUDE_CONFIG_DIR/logs/hooks.log` using the same helper the existing builtins use.

## Testing

Mirror the repo's test layout (`tests/unit/` + `tests/integration/`).

```
tests/unit/hooks/builtins/
├── test_pre_tool_use_security.py   [NEW]
└── test_post_tool_use_format.py    [NEW]

tests/integration/
└── test_security_hooks.py          [NEW]
```

### `test_pre_tool_use_security.py` — unit, table-driven

Roughly 30 cases via `pytest.parametrize`. Coverage plan:

- **Filesystem:** `rm -rf /`, `rm -rf /tmp/foo`, `rm -rf ./build` → block. `rm file.txt`, `rm -r dir` (no `-f`) → allow. `truncate -s 0 log.txt` → block.
- **Git:** `git push --force origin main` → block. `git push --force-with-lease origin main` → allow. `git reset --hard HEAD~3` → block. `git reset --soft HEAD~3` → allow. `git add -f .env` → block. `git add -f README.md` → allow.
- **SQL:** `DROP TABLE users`, `drop database prod` → block. `SELECT * FROM users` → allow.
- **Terraform:** `terraform destroy`, `terraform destroy -auto-approve` → block. `terraform apply -auto-approve` → block. `terraform apply` → allow. `terraform apply -replace=aws_instance.web` → block. `terraform state rm aws_instance.web` → block. `terraform plan` → allow.
- **Credentials:** `cat .env` → block. `cat .env.example` → allow. `cat .env.local` → block. `less ~/.ssh/id_rsa` → block. `cat ~/.ssh/id_rsa.pub` → allow (public key). `grep AWS_KEY ~/.aws/credentials` → block.
- **Allowlist rescue:** `rm -rf .worktrees/foo` with `allow_patterns=[r"\.worktrees/"]` → allow.
- **Invalid allow_pattern:** `allow_patterns=["(["]` + `rm -rf /tmp` → still block (broken regex skipped, real rules still apply).

### `test_post_tool_use_format.py` — unit

~6 cases using `mocker.patch("subprocess.run")`:

- Payload `Edit` on `.py` → subprocess called once with `["uv", "run", "ruff", "format", "/abs/path.py"]`, exit 0.
- Payload `Write` on `.py` → subprocess called once.
- Payload `Edit` on `.md` → subprocess NOT called, exit 0.
- Payload `Read` on `.py` → subprocess NOT called, exit 0.
- Malformed JSON stdin → subprocess NOT called, exit 0.
- `subprocess.run` raises `FileNotFoundError` (no ruff on PATH) → caught, log line written, exit 0.
- `subprocess.run` raises `subprocess.TimeoutExpired` → caught, log line written, exit 0.

### `test_security_hooks.py` — integration smoke (~4 cases)

Uses `subprocess.run` against the module as Claude Code would:

- PreToolUse block: payload matching `rm -rf /` → exit code 2, stderr contains `Blocked by lazy-harness PreToolUse` and `filesystem`.
- PreToolUse allow: payload `ls -la` → exit 0, stderr empty.
- PostToolUse smoke: payload with a `.py` tempfile → exit 0 (do not assert formatting happened; CI ruff availability varies).
- Empty stdin: both hooks → exit 0, no crash.

## Delivery plan

Single PR. File changeset:

- **New:** `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`
- **New:** `src/lazy_harness/hooks/builtins/post_tool_use_format.py`
- **Edit:** `src/lazy_harness/hooks/loader.py` — register the two new builtins.
- **Edit:** `src/lazy_harness/agents/claude_code.py` — add hook_event_map entries for `pre_tool_use` → `PreToolUse` (matcher `"Bash"`) and `post_tool_use` → `PostToolUse` (matcher `"Edit|Write"`), if not already present.
- **Edit:** `lh init` default template (exact path to confirm during implementation) — add the two `[hooks.*]` blocks with empty `allow_patterns = []`.
- **Edit:** `lh doctor` (if such a command exists — confirm during implementation) — add a check that warns if `ruff` is not on PATH, since the PostToolUse hook depends on it.
- **New:** three test files as described.
- **Edit:** `specs/backlog.md` — move the two items to Done.
- **Addendum or new ADR** on ADR-006 documenting the PreToolUse exit-2 divergence.

PR description includes the one-time snippet for `lazy` and `flex` profiles to paste into their `config.toml`.

## Open questions for implementation

1. The exact path of the `lh init` template that seeds new profiles' `config.toml`. The `Explore` pass identified the generator but not the template file itself. Worth a 5-minute dig during implementation before touching it.
2. Whether `re.IGNORECASE` should apply to the `.env` credentials rule to catch `.Env` / `.ENV` — likely yes but no real-world collision evidence.
3. Whether to treat `rm -rf ~/` as a separate extra-loud category. Arguably covered by the generic `rm -rf .+` pattern but worth a case in the tests.
