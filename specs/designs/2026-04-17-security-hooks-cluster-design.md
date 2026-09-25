# Security hooks cluster — design

**Date:** 2026-04-17
**Status:** implemented; security exception contract revised 2026-09-25
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
- Interactive confirmation. Hooks are non-interactive. A blocked operation must be reviewed; incidental text or a reworded command cannot grant an exception. Only an explicitly scoped literal cleanup has a configurable exception.

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

Policy lives in the shared harness `config.toml` and affects each profile reading
that file. The security options belong to the existing event table:

```toml
[hooks.pre_tool_use]
recursive_delete_roots = ["/absolute/project/.worktrees", "/absolute/scratch"]
denied_commands = ["example-cli"]

[hooks.post_tool_use]
scripts = ["post-tool-use-format"]
```

An omitted `scripts` key inherits default hooks; an explicit list replaces them,
and `scripts = []` opts out. Adding policy must preserve omission through both
new-document and existing-document save/load cycles. Neither policy list has a
nonempty default. No live profile migration happens automatically.

Legacy `allow_patterns` remains readable configuration, but the security hook
never evaluates it as an exemption. Replace reviewed cleanup regexes with
absolute roots; other regex exemptions have no automatic replacement. The
separate git-scope hook's allowlist is unaffected.

### Claude Code settings.json emission

The following was the initial April deployment sketch. Current deployments use
`lh hook`, normalized operations and wider file-tool subscriptions; see
[`docs/how/hooks.md`](../../docs/how/hooks.md#pre-tool-use-security-runs-on-pretooluse).
It is not a configuration template for the revised policy.

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

Category = Literal["filesystem", "sql", "terraform", "credentials", "git", "policy"]


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
    BlockRule("filesystem",  re.compile(_COMMAND_START + r"rm\s+(?=…recursive flag…)\S+.*"),                          "Recursive delete"),
    BlockRule("filesystem",  re.compile(_COMMAND_START + r"truncate\s+(-s\s+\d+\s+)?[^\s-]"),                         "File truncation"),
    BlockRule("git",         re.compile(_COMMAND_START + r"git\s+push\s+(--force(?!-with-lease)\b|-f\b)"),   "Force-push without lease"),
    BlockRule("git",         re.compile(_COMMAND_START + r"git\s+reset\s+--hard\b"),                                  "Hard reset discards work"),
    BlockRule("git",         re.compile(_COMMAND_START + r"git\s+add\s+(-f\b|--force\b)[^|;&\n]*(\.env|\.pem|\.key|\.p12|credentials|id_rsa|id_ed25519)"), "Forced add of secret"),
    BlockRule("sql",         re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.IGNORECASE),                    "SQL destruction"),
    BlockRule("terraform",   re.compile(_COMMAND_START + r"terraform\s+destroy\b"),                                   "Infra destruction"),
    BlockRule("terraform",   re.compile(_COMMAND_START + r"terraform\s+apply\s+[^|;&\n]*-auto-approve\b"),            "Skips plan review"),
    BlockRule("terraform",   re.compile(_COMMAND_START + r"terraform\s+apply\s+[^|;&\n]*-replace=\S+"),               "Forces resource recreation"),
    BlockRule("terraform",   re.compile(_COMMAND_START + r"terraform\s+state\s+(rm|push)\b"),                         "State mutation"),
    BlockRule("credentials", re.compile(_COMMAND_START + r"(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&\n]*(?<!\w)(?<!\w\\)\\?\.env\b(?!\.(example|sample|template))"), "Read of .env"),
    BlockRule("credentials", re.compile(_COMMAND_START + r"(cat|bat|less|more|head|tail)\b[^|;&\n]*\.ssh/id_\S+"),    "Read of SSH private key"),
    BlockRule("credentials", re.compile(_COMMAND_START + r"(cat|bat|less|more|head|tail)\b[^|;&\n]*\.aws/(credentials|config)\b"), "Read of AWS credentials"),
    BlockRule("credentials", re.compile(_COMMAND_START + r"(cat|bat|less|more|head|tail)\b[^|;&\n]*\.(pem|key|p12)\b"), "Read of cert/key file"),
)
```

Pattern authoring notes:

- The `[^|;&\n]*` guard prevents matches where the credentials path is on the *right* side of a pipe / semicolon / ampersand (i.e., legitimate commands that only reference a sensitive path as a pipe sink, such as `some-generator | tee out.pem`). The intent is to catch direct *reads*, not all mentions. The newline belongs in that class for the same reason the separators do: a command's arguments end at the line break, and without it a `cat` opening a heredoc on the first line reaches a secrets filename written in the body three lines down.
- The negative lookahead after `--force` permits the lease-only spelling. Token
  inspection also finds `--force`/`-f` after operands, short flag clusters and
  forced `+refspec`. A lease flag does not exempt an additional force flag.
- The `rm` rule matches **recursion alone**, in one lookahead. Force is not required and is not matched at all: `rm -rf`, `rm -fr`, `rm -r -f`, `rm --recursive --force`, `rm -r dir`, `rm -R dir`, `rm -r -- dir`, `rm -rv dir` all block; `rm -f file`, `rm -fv file`, `rm --force file`, `rm file` stay allowed. The lookahead is still keyed on the recursion letter rather than on a combined `-\S*f\S*`-style cluster, which would conflate the two and block every forced *single-file* delete under a "Recursive delete" label.
    - **Widened 2026-09-17, from a measurement rather than a preference.** It required recursion *and* force until then, so `rm -r dir` was allowed. Probe 6 (`codex-evidence.md` §4.2) put the same prompt — "a single recursive shell delete" — to the model three times and got `rm -rf` twice and `rm -r -- doomed` once; the guard blocked two of the three and the F9 acceptance gate's verdict became a coin flip on model phrasing. A rule whose verdict turns on the spelling a model happens to pick guards nothing.
    - The accepted cost is `rm -ri dir`, which prompts and now blocks anyway: the rule's subject is recursion, and an interactive confirmation is not something the pattern can read.
- **Every rule whose token names an executable is anchored to a command position** (`_COMMAND_START`: start of a *line*, after `;`/`&`/`|`/`(`/backtick, or after a wrapper that execs its argument — `sudo`/`xargs`/`eval`/`sh -c` and its flag-cluster spellings such as `-lc`), with an optional leading path so `/bin/rm` still matches, and an optional quote so a command inside an interpreter's own string — `python3 -c '… os.system("…")'` — is still reached. Without that anchor a pattern also fires on commands that merely *mention* the token inside a quoted argument — `grep -rn "rm -rf" src`, `git commit -m "fix: rm -rf guard"`, `herdr agent prompt <pane> '<prose>'` — which is the dominant false-positive class in practice, measured three times against `terraform destroy` alone.
    - `sql` is the single deliberate exemption: `DROP TABLE` is never the executable, it is the argument of one (`psql -c "DROP TABLE users"`), so anchoring it would delete the rule rather than narrow it. The cost is that prose naming `DROP TABLE` still trips it.
    - `(?m)` is what makes `^` mean start-of-line, so a command on the second line of a multi-line script — or of a heredoc body piped into a shell — stays in command position. It has to sit at index 0 of the expression: Python accepts a global inline flag only at the start.
    - **Limits.** Static inspection cannot trace dynamically constructed executable
      names, arbitrary interpreters or every shell expansion. Quoted command
      substitutions and `env -S` remain outside the opt-in command policy. This
      is not an OS execution boundary. The previously documented force-push
      ordering escape is closed: `git push origin main --force` now blocks.
- `re.IGNORECASE` only on the SQL patterns — SQL is case-insensitive by convention; the rest are shell tokens that are case-sensitive.

**Pure logic and exception boundary:**

`should_block` accepts legacy `allow_patterns` for call compatibility, but never
uses them to rescue a match. `denied_commands` is checked in recognized command
positions. Existing regex rules and tokenized rm/git arguments then determine
whether an operation is destructive.

Only the recursive-delete rule can be exempted by `recursive_delete_roots`.
`_safe_cleanup` accepts one simple literal rm invocation and verifies **every**
operand resolves strictly below an allowed root. It resolves symlinks at both
ends, rejects the root itself, traversal and sibling-prefix paths, and uses the
event cwd for relative operands. Quoted spaces, reordered flags and multiple
allowed operands work; wrappers, operators, redirections, expansions, globs and
unknown flags never qualify. Filesystem state must remain trusted between
inspection and execution.

This closes the incidental-path reset bypass, a mixed safe/unsafe deletion, and
pipeline rescue. An exception never transfers to another rule or operation.

**Entry point:** `main(event: HookEvent) -> HookDecision` consumes normalized
operations. It returns `Verdict.DENY` on a refusal and abstains otherwise; adapters
produce the native protocol (Claude Code stderr/exit 2, Codex JSON/exit 0). File
reads and edits retain the independent secret-path guard and its sample/public
key exceptions. Cleanup roots do not exempt file-tool secret paths.

**Block message format** (stderr, consumed by Claude Code and surfaced to the agent):

```
Blocked by lazy-harness PreToolUse: <reason> (<category>).
Matched: <truncated matched_text, max 120 chars>
Review [hooks.pre_tool_use] in config.toml. Only recursive_delete_roots can exempt a literal cleanup; legacy allow_patterns no longer bypass security rules.
See specs/designs/2026-04-17-security-hooks-cluster-design.md for the full rule list.
```

**Policy loading** (`_load_policy()`): resolve the harness config through
`core.paths.config_file`, read only its local `[hooks.pre_tool_use]` table, and
call `core.config.parse_security_policy`, the same parser the central config
loader invokes. `ConfigError` becomes a denial without loading unrelated
configuration. Missing files
or sections mean empty policy lists. Unreadable or malformed files, invalid
table shapes, unknown keys and invalid policy values refuse command execution.
Existing size-limit keys remain valid in this shared event table.

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

1. The runner parses the provider payload into a normalized tool operation.
2. Command operations load policy and invoke `should_block`; read/edit operations
   inspect every path through the secret-path guard. Other operations abstain.
3. A scoped cleanup can skip only the recursive-delete rule. Other matches still
   deny; arbitrary regex text never grants permission.
4. The adapter serializes a denial or silent abstention for the calling provider.

**PostToolUse path:**

1. Claude Code emits `{"tool_name": "Edit" | "Write", "tool_input": {"file_path": "..."}}`.
2. Non-Edit/Write or non-`.py` → `sys.exit(0)` silently.
3. `ruff format <path>` via `uv run`, with `check=False` (errors do not raise).
4. `sys.exit(0)` always.

## Error handling

| Failure mode                               | PreToolUse behavior                               | PostToolUse behavior       |
|--------------------------------------------|---------------------------------------------------|----------------------------|
| Malformed stdin JSON                       | Runner refuses unusable input for this blocking hook | `sys.exit(0)`              |
| `config.toml` missing                       | Empty policy lists; no cleanup exemption          | N/A                        |
| `config.toml` unreadable / malformed        | Deny command execution with a policy diagnostic   | N/A                        |
| Regex compile error in code                | Caught at import-time by tests                    | N/A                        |
| Legacy `allow_patterns`                    | Ignored for security exemptions, including invalid regexes | N/A                  |
| Invalid policy key/value                   | Deny with a diagnostic naming the key             | N/A                        |
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

- **Filesystem:** `rm -rf /`, `rm -rf /tmp/foo`, `rm -rf ./build`, `rm -fr ./build`, `rm -r -f ./build`, `rm --recursive --force ./build`, `sudo rm -rf …`, `/bin/rm -rf …`, `cat list | xargs rm -rf`, `rm -r dir`, `rm -R dir`, `rm -r -- dir`, `rm -rv ./build`, `/bin/zsh -lc 'rm -r -- doomed'` → block. `rm file.txt`, `rm -f file.txt` (no recursion), `rm -fv file.txt`, `rm --force file.txt`, `git rm -r --cached .` (`rm` is not in command position) → allow. `grep -rn "rm -rf" src` and `git commit -m "fix: rm -rf guard"` (mention, not invocation) → allow. `truncate -s 0 log.txt` → block.
    - **Open false positive, measured 2026-09-17 and not closed.** A quoted argument that itself contains a shell-operator character ahead of the token reaches `_COMMAND_START` through the operator alternative, not through the mention: `grep -rn 'a\|rm -rf\|b' tests/` blocks while `grep -rn "rm -rf" src` does not. It predates the widening above — the `-rf` spelling always blocked — and closing it needs quote-awareness the anchor does not have.
- **Git:** `git push --force origin main` → block. `git push --force-with-lease origin main` → allow. `git reset --hard HEAD~3` → block. `git reset --soft HEAD~3` → allow. `git add -f .env` → block. `git add -f README.md` → allow.
- **SQL:** `DROP TABLE users`, `drop database prod` → block. `SELECT * FROM users` → allow.
- **Terraform:** `terraform destroy`, `terraform destroy -auto-approve` → block. `terraform apply -auto-approve` → block. `terraform apply` → allow. `terraform apply -replace=aws_instance.web` → block. `terraform state rm aws_instance.web` → block. `terraform plan` → allow.
- **Credentials:** `cat .env` → block. `cat .env.example` → allow. `cat .env.local` → block. `grep -rn "process\.env" src/` → allow (an identifier ending in `.env` is an API, not the dotenv file; the escaped dot is how such a grep is usually written). `less ~/.ssh/id_rsa` → block. `cat ~/.ssh/id_rsa.pub` → allow (public key). `grep AWS_KEY ~/.aws/credentials` → block.
- **Legacy allowlist:** broad, matching and invalid regexes never rescue a denial.
- **Scoped cleanup:** every literal operand must resolve strictly below an
  explicit root; test mixed destinations, symlinks, root aliases, quoted paths,
  whitespace, flag order and ambiguous shell syntax.
- **Environment policy:** opt-in executable names block in recognized command
  positions and wrappers; mentioning a name in ordinary prose stays allowed.
- **Persistence:** full load/save/load/save/load cycles through the hook consumer
  for new and existing destinations, including inherited scripts and size keys.
- **Adversarial coverage:** targeted guard mutations must make these tests fail.

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
- **Configuration:** new policy lists default to empty; preserve default hook
  inheritance when an event table adds policy without an explicit scripts list.
- **Edit:** `lh doctor` (if such a command exists — confirm during implementation) — add a check that warns if `ruff` is not on PATH, since the PostToolUse hook depends on it.
- **New:** three test files as described.
- **Edit:** `specs/backlog.md` — move the two items to Done.
- **Addendum or new ADR** on ADR-006 documenting the PreToolUse exit-2 divergence.

PR description includes the one-time snippet for `lazy` and `flex` profiles to paste into their `config.toml`.

## Open questions for implementation

1. The exact path of the `lh init` template that seeds new profiles' `config.toml`. The `Explore` pass identified the generator but not the template file itself. Worth a 5-minute dig during implementation before touching it.
2. Whether `re.IGNORECASE` should apply to the `.env` credentials rule to catch `.Env` / `.ENV` — likely yes but no real-world collision evidence.
3. Whether to treat `rm -rf ~/` as a separate extra-loud category. Arguably covered by the generic `rm -rf .+` pattern but worth a case in the tests.
