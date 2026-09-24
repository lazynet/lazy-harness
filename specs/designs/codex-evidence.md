# Codex dialect evidence — payload schema, command parsing, response format, state keying

**Status:** probes run 2026-09-16 against `codex-cli 0.154.0` (model
`gpt-6-astra`), from an Aqua terminal, in two rounds. §1, §2, §3 and the F8
reconciliation below are closed against the real binary. The first round's
deny probe used a malformed envelope and produced a misleading reading (a
native edit path that looked unhooked); the second round, probes 4b and 4c,
used a validated envelope and corrected it — see §3 and the F8 section for what
changed and why. §4 (state keying) was not exercised by either round and stays
as originally scoped. §8 (exit 2 as a refusal channel) was run 2026-09-24
against `codex-cli 0.155.1`, closed for `Bash` on `PreToolUse` with empty
stdout; `apply_patch` and other exit codes/events not run — see §Pendiente.
**Binary:** `codex-cli 0.154.0` (local: confirmed via `codex --version`, 2026-09-16).
**Scope:** step 9's `CodexAdapter` implements `system_docs()` on its own lane. This
document owns one thing only, per ADR-041's evidence standard — *"a name in a
binary is evidence of a name, and of nothing else"* — for the one gap the F8
gate names in its own header as unresolved: **what Codex's real wire dialect is
for a file edit**, as opposed to the shell command the adapter has actually
observed.

**Why an edit and not another command.** `CodexAdapter._TOOL_OPERATIONS`
(`src/lazy_harness/agents/codex.py:92`) maps exactly one native tool name,
`Bash -> RUN_COMMAND`, and the docstring above it says why: "the shell tool was
exercised, so only the shell tool is mapped — a tool absent here parses with
`operation=None`". Every other contract question below (payload shape, verdict
envelope, trust key) had already been run against the binary before this
document existed, and is cited from `specs/adrs/041-multi-agent-hook-contract.md`
and `specs/designs/2026-09-13-multi-agent-harness-design.md`. Only the edit
dialect had zero runs behind it going in — `apply_patch` appeared in the design
doc's provider table tagged `(source)`, never `(run)` or `(log)`. Six probes
across two rounds below closed §1, §2 and §3.

Claude Code's own session policy refused `codex exec` on 2026-09-16 before it
ran (recorded in `specs/backlog.md`'s F8 entry and in `translation-gate.sh`'s
own header), so the probes below were run by hand from an Aqua terminal on the
same date, against the real binary, and the raw output pasted back in. The
first round (probes 1-4) closed §1 and §2 but produced one misleading reading
in §3: probe 4's deny hook built its verdict with a hand-escaped `echo`
one-liner, and a malformed envelope reads to Codex as an unsupported
`permissionDecision`, which ADR-041 already documents as **failing open** —
so the edit going through said nothing about whether the hook fired, only that
its (invalid) verdict didn't block. The second round (probes 4b and 4c) used a
validated, `json.dumps`-built envelope and corrected the reading. Recorded
below is the corrected conclusion, not the first round's — with the first
round's mistake named, since it changed what the F8 section below concludes.

## 1. Payload schema

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Event envelope | Design doc line 431-441: snake_case, `hook_event_name`, `transcript_path`, `tool_name`, `tool_input`, `tool_use_id` — captured **for a `Bash`/`PreToolUse` call**, `(run, 0.154.0)`. | `parse_hook_input` (`codex.py:147-176`) reads exactly those keys via `isinstance` guards; docstring calls the shape "Claude-shaped, and that is an observation, not an assumption" — but the observation backing it is the Bash payload above. | **Confirmed identical, run 2026-09-16.** Probe 1's `PreToolUse` record for a file-edit prompt: `session_id`, `turn_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `tool_name`, `tool_input`, `tool_use_id` — the same key set, same casing, as the design doc's Bash capture quoted above. No key was added or dropped for an edit prompt. `PostToolUse` adds one key, `tool_response` (observed as `""` in this run). Every key `parse_hook_input` reads was present. (The probe run's own notes flagged these as "extra keys beyond the design doc's capture" — checked against the doc's quoted payload at line 435-441 and that's not accurate: the design doc's Bash capture already carries every one of these keys. Recorded here as confirmation, not discrepancy.) |
| `tool_input` shape for an edit | Not run. Design doc line 1009 only asserts *that* `apply_patch` can touch several files in one call, not the field names it arrives with. | `_parse_tool` (`codex.py:178-191`) reads `arguments.get("command")` — a field that makes sense for `Bash`, not for an edit. For any other tool name it stores `raw_input=arguments` unread. | **Resolved for both edit paths.** For the `Bash`-mediated edit, `tool_input` is `{"command": "<python heredoc>"}` — ordinary `Bash` shape. For the native `apply_patch` path (probe 4c, forced by prompt and confirmed with a validated deny that blocked it), `tool_input` is **also** `{"command": "<raw patch text>"}` — the *same key*, `command`, but the value is a full patch blob: `*** Begin Patch\n*** Update File: <abs path>\n@@\n-old\n+new\n*** End Patch`. There is no structured path/old-text/new-text field; the touched path is embedded as a `*** Update File: <path>` line inside the blob text. `_parse_tool`'s existing `arguments.get("command")` read technically captures this string for `apply_patch` too — it just has no idea it's a patch rather than a shell command, and does nothing to extract the path from it. |
| `hook_event_name` value for the same call | Design doc's Bash capture shows `"hook_event_name":"PreToolUse"`. | `_HOOK_EVENTS["pre_tool_use"] = HookSupport("PreToolUse", ...)` (`codex.py:81`) — assumes the event name is stable across tool types, which is a reasonable inference but unverified for an edit specifically. | **Confirmed for both edit paths.** `"PreToolUse"` fired with `tool_name: "Bash"` for the heredoc edits, and — once probe 4c used a validated deny so the block was actually observed — `"PreToolUse"` also fired with `tool_name: "apply_patch"` for the native path, and the block took effect (`target.txt` stayed `"untouched"`, transcript logged `Command blocked by PreToolUse hook`). The first round's reading that the native path produced no `hook_event_name` at all was an artefact of that round's malformed deny envelope (Codex fails open on an invalid `permissionDecision`, so the edit proceeding said nothing about whether the hook fired) — **withdrawn**, corrected here. |

## 2. Command / tool-call parsing

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Native tool name for an edit | Design doc line 1196 (provider table): `apply_patch`, tagged **`(source)`** — read off Rust source, never exercised. Contrast `Bash`, tagged `(run)` at the same table and confirmed again at line 1048: `exec_command` normalises to `"Bash"` on the wire. | `_TOOL_OPERATIONS = {"Bash": Operation.RUN_COMMAND}` (`codex.py:92`) has no entry for whatever the edit tool's native name turns out to be, so `operation` comes back `None` for it regardless of what that name is. | **Resolved: both candidates are real, and Codex picks between them non-deterministically.** Six runs, model `gpt-6-astra`, two rounds: most edits go through `Bash` (a python heredoc, `tool_name: "Bash"`), and — confirmed by probe 4c, which forced the model toward a native edit and used a *validated* deny to prove the hook actually saw it — Codex also uses a genuine `apply_patch` tool, firing `PreToolUse` with `tool_name: "apply_patch"` literally. (The first round's reading that this second path produced no hook payload at all was wrong — see the note on §1 above; it was a malformed-envelope artefact, not evidence of an unhooked path.) **`_TOOL_OPERATIONS` has a real gap now**: `apply_patch` is not in it, so an edit taking that path still parses with `operation=None` today. Mapping it to `MODIFY_FILE` is necessary — see the F8 reconciliation below for why it's not sufficient. |
| Downstream field construction (`reads` / `edits`) | `ToolCall.edits: tuple[FileEdit, ...] = ()` and `.reads: tuple[Path, ...] = ()` (`agents/base.py:87,91`) — both default empty, populated per-adapter. | `CodexAdapter._parse_tool` never sets either field — confirmed by reading the method (`codex.py:178-191`): it returns a `ToolCall` with only `native_name`, `operation`, `command`, `raw_input` set. `edits` and `reads` are always `()` under `CodexAdapter`, independent of `tool_name`. | **Confirmed, and now the load-bearing finding rather than a side note.** `apply_patch`'s `tool_input` is `{"command": "<patch blob>"}` (§1) — the *same key* `_parse_tool` already reads for `Bash`. So even after mapping `apply_patch -> MODIFY_FILE`, `_parse_tool` would read the blob into `command` and still leave `edits`/`reads` empty, because nothing parses the blob's `*** Update File: <path>` lines into a `FileEdit`. Two fixes are needed, not one: the `_TOOL_OPERATIONS` entry, **and** a parser for the patch-blob text. Neither alone revives the five builtins gated on `tool.edits`. |
| Multi-file edits in one call | Design doc line 1009: "Codex's `apply_patch` … can touch several files in one call". Cited from the same source-only evidence as the tool name. | N/A — nothing reads `tool_input` for edits at all yet. | **Confirmed for `Bash`, untested for `apply_patch`.** Probe 3 (append `ALPHA` to `a.txt`, `BETA` to `b.txt` in the same turn) produced exactly two `PreToolUse` records for the whole turn: one discovery `rg --files` call, and one `Bash` python-heredoc call whose loop edited *both* files in a single `command` string. No probe forced a multi-file `apply_patch` call, so whether its patch-blob format concatenates multiple `*** Update File:` sections in one `command` string (plausible, given the design doc's `apply_patch` claim) or Codex always splits multi-file patches into separate hook calls is still open — lower priority than closing §4, since a parser for the single-file blob is the harder, necessary-first piece regardless. **Resolved 2026-09-16 (probe 5, `codex-cli 0.154.0`, model `gpt-5.6-sol`).** One `PreToolUse` record for the whole turn, `tool_name: apply_patch`, one blob between a single `*** Begin Patch`/`*** End Patch` pair carrying two `*** Update File:` sections, one per touched file — both files changed on disk. Codex concatenates a multi-file `apply_patch` edit into one blob; it does not split multi-file patches into separate hook calls. `_parse_patch` (shipped in #348) already parses N sections generically and carries a two-section test — nothing to change. |
| Delete spelling (`*** Delete File:`) | ADR-044's Consequences (`specs/adrs/044-codex-native-edit-path.md`): widening `FileEdit` for a delete is undecided because "the delete spelling is the patch format's, not one any probe has seen Codex emit." | N/A — `FileEdit` has no delete counterpart and nothing constructs one. | **Measured 2026-09-16 (probe 6, model `gpt-5.6-sol`).** One `PreToolUse` record, `tool_name: apply_patch`, blob is a single `*** Begin Patch`/`*** End Patch` pair with one section, literal header `*** Delete File: <abs path>` — no diff body under it. The target file was removed from disk. The spelling ADR-044 flagged as unprobed is now on record; widening `FileEdit` for it is unblocked and tracked as its own backlog item, not done here. |

## 3. Response format (verdict envelope)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Refusal envelope, `PreToolUse` | Design doc line 408-421 and `codex.py:193-227`'s own docstring: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`, stdout, exit 0 — **observed for a `Bash` refusal**: the file the model was told to create was never created, `codex exec` echoed the reason back verbatim. | `format_hook_output` builds the identical envelope regardless of which tool triggered the hook — there is nothing tool-specific in the function, so the envelope itself is not in question. | **Resolved: the deny contract is correct for both edit paths. The first round's "no effect" reading was a test artefact, not a Codex defect.** Probe 4 (hand-escaped `echo {...}` deny verdict) let a `Bash`-mediated edit through — `target.txt` read `touched`, no block text anywhere in the transcript. Probe 4b re-ran the identical scenario with a `json.dumps`-built verdict from a file (no hand-escaping): `target.txt` stayed `untouched`, and the transcript logged `error=Command blocked by PreToolUse hook: codex-evidence probe 4b: deny-all (validated envelope). Command: pwd; rg --files ...`. Probe 4c forced a native edit and used the same validated envelope: `target.txt` stayed `untouched` again, `pre_tool_use.jsonl` recorded `tool_name: "apply_patch"`, and the transcript logged the same `Command blocked by PreToolUse hook` line, this time echoing the patch blob back as the blocked command. **Conclusion:** probe 4's malformed `echo` JSON reached Codex invalid, and per ADR-041's own documented behaviour for an unsupported/invalid `permissionDecision`, Codex **failed open** — exactly as that ADR predicts, not a new finding about Codex, a confirmation of one already on record. With a valid envelope, `deny` blocks both edit paths identically. |
| `allow` / `ask` on an edit | ADR-041 §"a hook whose verdict the agent will not honour": `allow` without `updatedInput` and `ask` are both rejected as `"unsupported permissionDecision"` and Codex **fails open** — observed for `PreToolUse`/`Bash` (`codex.py:66-71`). `_HOOK_EVENTS["pre_tool_use"].verdicts == frozenset({Verdict.DENY})` (`codex.py:81`) already encodes only `deny` as honoured, for any tool. | Same code path handles every tool identically — `format_hook_output` raises `ValueError` before emitting anything Codex hasn't been shown to honour, so there is no tool-specific branch to falsify here either. | **Not run — no longer blocking anything.** The row above closes the question this row exists to sanity-check for edits specifically (deny works, on both paths); `allow`/`ask` failing open was already established for `Bash` (`codex.py:66-71`) and there's no new reason, after confirming `deny` behaves identically across tools, to expect `allow`/`ask` to differ by tool. Worth a confirmation run only if a future change makes the harness emit `allow`/`ask` for Codex at all — nothing does today. |

## 4. State keying (hook trust)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Trust key shape | Design doc line 763-779: `<absolute path of declaring file>:<snake_case event>:<group index>:<handler index>` — path-scoped, **measured** on 0.154.0 with a `PreToolUse`/`Bash` hook (the byte-identical-handler probe that found `hooks.json` trusted while the identical `config.toml` declaration read `new · review required`). | `codex.py:104-109` states the choice ("hooks.json") is "frozen at the first deploy" on the strength of that same measurement — the key is derived from *event name and position in the file*, not from the tool the hook happens to guard. | **Resolved 2026-09-17 (matcher probe 13:22 + hook-exec probe 14:34, `codex-cli 0.154.0`, model `gpt-6-astra`). The non-finding was a finding: the key is tool-independent, and a matcher naming a tool is honoured.** Five `PreToolUse` groups differing only in their `matcher` were declared in one `hooks.json`, trusted in one pass, and each fired or stayed silent according to its own literal on the same call — so trust is keyed by `<file>:<event>:<group index>:<handler index>` as the design doc says, with nothing tool-derived in it, and a group's matcher decides *whether* it is consulted without changing *how* it is trusted. The hook-exec probe then trusted five groups via `--dangerously-bypass-hook-trust` and got identical behaviour, so the bypass flag and a TUI approval produce the same dispatch. **Closed 2026-09-17 16:41 by probe 6 (§4.2).** 31 real `hooks.state.` entries approved through the TUI behave like five bypassed ones: with no bypass flag and the real trust store, `pre-tool-use-security` was *invoked* (`1 -> 2`) and answered allow. An unapproved group is never dispatched, so the stored approvals cover the group that matters and trust is not a delta anywhere in this table. |
| Matcher on a named tool | `_hook_groups`'s own docstring (`codex.py:276-281`): "An empty string was never observed, and the observed form that fires on every tool call is the one with no key at all." | The harness currently emits no per-tool matchers for Codex at all — every builtin gets an unconditional group. | **Resolved 2026-09-17 13:22 (matcher probe, `codex-cli 0.154.0`, model `gpt-6-astra`). It is a regex, it is matched against the Claude-compatible alias as well as the native name, and every group is evaluated.** Two turns — a shell call reporting `tool_name: Bash` and a native edit reporting `tool_name: apply_patch` — against four spellings in one file, matcher-less control rendered last so that a run in which nothing else fired could still tell first-match-wins from every-other-matcher-failing:<br><br>`Bash\|Read\|Edit\|Write\|NotebookEdit` fired on **both**. `^Bash$` fired on `Bash` and **not** on `apply_patch`, so the anchors work and it is not substring or literal equality. `Edit\|Write` fired on **`apply_patch`**, so Codex evaluates the matcher against a tool's Claude-compatible alias as well as against the native name the payload carries. The matcher-less control fired on both turns *alongside* the matching literals, so evaluation does not stop at the first match.<br><br>**Consequence for the harness, and it is the opposite of what this row assumed:** the deployed literal `Bash\|Read\|Edit\|Write\|NotebookEdit` — written for Claude Code's vocabulary and declared once per builtin in `hooks/loader.py` — already covers both of Codex's tool paths. The eight groups the harness deploys are not suppressed, and no Codex-specific matcher is needed. ADR-056 records the decision to keep them agent-agnostic. `_hook_groups`'s docstring remains correct about the *empty* form; what it could not say is that a non-empty Claude-shaped one also fires. |

### 4.1 Probe 5 — the hook-exec table, corrected

Ran 2026-09-17 14:34 from an Aqua terminal, `codex-cli 0.154.0`, model
`gpt-6-astra`, one turn (the `rm -rf` fixture F9 phase B uses), five `PreToolUse`
groups all carrying the deployed matcher: three that capture and swallow stdout,
two that answer Codex, one bare-`lh` and one absolute-path each.
`--dangerously-bypass-hook-trust`, throwaway `CODEX_HOME`, throwaway
`LH_CONFIG_DIR`.

**The summary the probe printed at 14:34 is not reproduced here, because three of
its four readings were wrong.** The records on disk were right every time; the
reader was pointed at the wrong config, the wrong stream and the wrong directory.
The bugs and their fixes are in the commit that adds ADR-056; the table below is
what the records say.

| Variant | `lh` spelling | stdout to Codex | exit | stdout | `command -v lh` in the hook |
|---|---|---|---|---|---|
| `diag` | — | no | n/a (records env only) | — | `/…/.local/bin/lh` |
| `capture-abs` | absolute | no | 0 | valid envelope, `permissionDecision: "deny"`, reason present | `/…/.local/bin/lh` |
| `capture-bare` | bare `lh` | no | 0 | valid envelope, `permissionDecision: "deny"`, reason present | `/…/.local/bin/lh` |
| `live-abs` | absolute | yes | 0 | valid envelope, `permissionDecision: "deny"`, reason present | `/…/.local/bin/lh` |
| `live-bare` | bare `lh` | yes | 0 | valid envelope, `permissionDecision: "deny"`, reason present | `/…/.local/bin/lh` |

Outcome: **the fixture directory survived.** Codex's own refusal is on
`stream.stderr`, line 1:

```
ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: Blocked by lazy-harness PreToolUse: Recursive delete (filesystem).
Matched: rm -rf -- doomed
```

The `--json` stream carries no such line. It carries the model's account of it,
as `item_3`:

```
Automatic approval review blocked `rm -rf -- doomed` because recursive
filesystem deletion is disallowed. The directory was not deleted.
```

**Reading the table.** The four candidates the probe was built to separate are
each falsified by a cell in it:

* **(a) the bare name does not resolve.** `capture-bare` and `live-bare` both
  exit 0 with a valid envelope, and `command_v_lh` in every `env.txt` is the
  installed binary. A bare `lh` resolves in the environment Codex spawns a hook
  into, which no earlier probe had ever exercised.
* **(b) the hook runs, crashes and exits 0.** Exit 0 *with* a valid deny
  envelope on every variant. The failure mode this repo gates on — a blocking
  hook exiting 0 with nothing on stdout — did not occur.
* **(c) the payload differs.** `records/*/stdin.json` carries
  `hook_event_name: PreToolUse`, `tool_name: Bash`, `tool_input.command`,
  `session_id`, `turn_id`, `transcript_path`, `cwd`, `model: gpt-6-astra`,
  `permission_mode: bypassPermissions`, `tool_use_id` — the shape §1 records.
* **(d) Codex ignores the verdict.** It does not: the directory survived and the
  router logged the refusal. **Where** it surfaces is the new fact — Codex
  consumes a `PreToolUse` deny in its **approval-review stage**, reporting the
  harness's own reason on stderr while the JSON stream carries only the model's
  prose about it. A consumer looking for the mechanism must read stderr.

**One `CODEX_HOME` means one hook log.** The probe declared three throwaway
profiles so their log counts would attribute per group, and `agent_runtime_dir`
(ADR-032 L3) resolves the adapter's env var before the profile's `config_dir` —
so all three wrote to `$CODEX_HOME/logs/hooks.log` and the per-profile split did
not survive. Per-group attribution is `records/<label>/`, which is per-label by
construction.

**Where that stderr line lands in the gate's own capture** is §6.4, measured on
the acceptance run of 2026-09-18: `codex_turn` redirects the turn with `2>&1`,
so the refusal sits inside `stream-<label>.jsonl` between two JSON rows. §6.4
also records the fact this probe's stream shape already implied and nothing had
stated — Codex emits **no** `command_execution` item for a command its
`PreToolUse` hook blocked, so the block line is the only record of it.

**What this leaves.** Probe 5 blocked; the F9 live run of 12:32 did not. Three
deltas remain between them — the deployed `hooks.json` (8 real groups, including
`moshi` and `graphify hook-guard`, against 5 hand-rendered), the trust store (31
TUI-approved `hooks.state.` entries against `--dangerously-bypass-hook-trust`),
and the driver (the F9 live path against `codex exec`).
`specs/gates/probes/codex-hook-probe6.sh` separates them, and §4.2 is what it
measured.

### 4.2 Probe 6 — the three deltas, and the one that was never a delta

Ran 2026-09-17 16:41 from an Aqua terminal, `codex-cli` 0.154.0, against the
**real** `~/.codex-lazy` with its 31 TUI-approved `hooks.state.` entries and the
8 deployed groups. Artifacts: `/tmp/hook-probe6/stream-{a,b}.{jsonl,stderr}` and
`~/.codex-lazy/logs/hooks.log` 16:41:17–16:41:32.

| arm | flag | the command the model issued | `pre-tool-use-security` | fixture |
|---|---|---|---|---|
| A | none — real trust | `/bin/zsh -lc 'rm -r -- doomed'` | `invoked` (1 → 2), no block line | **deleted** |
| B | `--dangerously-bypass-hook-trust` | `rm -rf -- doomed` | `invoked` + `blocked filesystem` | survived |

**The verdict the probe printed — "A allowed and B blocked: TRUST" — is wrong,
and the probe's own readings are what falsify it.** `pre-tool-use-security` was
*invoked* in arm A. An unapproved group is never dispatched, so the 31 stored
approvals cover the group that matters and trust was never the delta. The hook
ran and answered allow.

It answered allow because the guard was written to. The recursive-delete rule
required recursion **and** force, so a recursion-only spelling was permitted by
design. Measured in process through the shipped runner against profile
`lazy-codex`, before the change below:

```
rm -r -- doomed        -> allow (no envelope, exit 0)
rm -R doomed           -> allow
rm --recursive doomed  -> allow
rm -rf -- doomed       -> deny
rm -r -f doomed        -> deny
rm -fr doomed          -> deny
```

**So the 12:32 F9 FAIL was a fired-but-allowed on a permitted spelling — not a
hook defect, not trust, not the driver.** F9 phase B and this probe use the same
prompt, "a single recursive shell delete"; the model answered `rm -rf` twice
(probe 5, arm B) and `rm -r` once (arm A). The gate's `denied / allowed` verdict
was a coin flip on model phrasing, and both the gate and this probe reported the
losing toss as a defect in the thing they were measuring.

Three things changed as a result, all in the same commit as this section:

* **The rule widened.** Recursion alone now denies; force is not matched at all.
  `2026-04-17-security-hooks-cluster-design.md` carries the decision and the
  accepted cost. This removes the coin flip at the source.
* **Phase B judges the contract, not the fixture.** It reads the issued command
  off the `--json` stream, replays it through the shipped guard, and compares
  that verdict against what happened on disk — `specs/gates/guard_contract.py`.
  A spelling the guard permits is reported as inconclusive and re-prompted once,
  never as a FAIL.
* **The probe gained the fired-but-allowed row.** `TRUST` is now only reachable
  when arm A shows *no* invocation delta.

**The "profile moved under the probe" alarm was benign and is now silenced.**
`hooks.json` was byte-identical (`7ba1c7bd` → `7ba1c7bd`) and so were the
`hooks.state.*` tables. What moved was Codex's own state: it wrote
`[projects."/private/var/.../tmp.*"] trust_level = "trusted"` for each throwaway
workspace and bumped a usage counter. Two such stale `[projects.*]` entries now
sit in the real `~/.codex-lazy/config.toml` and can be deleted by hand. The
probe's fingerprint covers `hooks.json` and `hooks.state.*` only.

**The driver delta, closed on run 4.** This probe never reached it — arm A closed
the question arm B existed to split — so it fell to the acceptance gate's own live
path. Run 4 drove that path end to end on 2026-09-18 08:27 (`lh` 0.71.1,
`codex-cli` 0.154.0) and returned 17 assertions, 0 failed, 0 blocked, 2 not
observed, with both NO-OBS closing on the run's own recorded artifacts rather than
on a fifth run (§6.4). Phase B telling a permitted spelling from an ignored verdict
is what made that run readable. All three deltas are measured; none is outstanding.

### 4.3 Trust survives a release: 0.154.0 → 0.155.0

The 31 `[hooks.state."<key>"].trusted_hash` entries in
`~/.codex-lazy/config.toml` were written by TUI approval under `codex-cli`
0.154.0 during probe 6 on 2026-09-17 16:41 (§4.2). Brew installed
`codex-cli` 0.155.0 on 2026-09-18 18:20, and no Codex session ran between the
upgrade and this measurement.

At 18:54, `lh deploy --profile lazy-codex` under lazy-harness 0.72.1 rewrote
`hooks.json` byte-identically: its sha256 was `7ba1c7bd…` before and after. All
31 state entries survived, and a diff against the deploy snapshot was
identical.

The first 0.155.0 session started at 18:59:07 with
`lh run --profile lazy-codex --bypass=activate -- -c
model_reasoning_effort=medium` in a worktree of this repository. That bypass
does **not** pass `--dangerously-bypass-hook-trust`: `agents/codex.py:995`
deliberately excludes it from every bypass row because hook trust is a
different axis from approvals and sandboxing. Dispatch therefore depended on
the stored trust alone.

No hook review screen appeared at startup in the 18:59 pane read. `hooks.log`
records `18:59:38 session-context: fired` and `injected 4302 chars` for
SessionStart; at 19:01:42 it records `session-export: fired`,
`compound-loop: fired`, and a queued task for Stop. The TUI status line showed
`Running hooks`. After the session, `config.toml` still had its 18:54 mtime and
all 31 hashes were unchanged.

PreToolUse dispatch is not observable in `hooks.log`:
`pre-tool-use-security` logs only blocks, apart from the explicit `invoked`
mode used by the F9 gate. The observation therefore covers SessionStart and
Stop groups. The trust key is per group and carries nothing event-specific
(§4, row 1), so the normalisation that held for those groups held for the
file.

Decision 5's option (b) stands and gains its first cross-release data point;
option (a) stays rejected. One release pair is not a guarantee: this row
re-opens if a future upgrade shows the review screen for an unchanged
`hooks.json`. `lh doctor` is unchanged and still reports `31 hooks carry a
stored hash` as `unknown`, by design.


## Probes a correr

Probes 1 through 4, then 4b and 4c, all ran 2026-09-16 from an Aqua terminal,
against `codex-cli 0.154.0`, model `gpt-6-astra`; their raw output is folded
into §1-§3 above. They're kept below verbatim for reproducibility, and because
Probe 4's own malformed envelope is part of the record — it's what the F8
section below cites when explaining why the first-round reading needed
correcting. Run these from an Aqua terminal if reproducing. Each is
self-contained and creates its own disposable `CODEX_HOME`. **Do not run
`codex exec` from inside a Claude Code session** — that's the policy that
blocked the 2026-09-16 attempt before any of this, and re-hitting it from here
just burns another attempt for no new evidence.

Auth lives at `~/.codex/auth.json`; a disposable `CODEX_HOME` needs it copied in
or `codex login` run again inside it. All six probes copy it.

### Probe 1 + 2 — payload schema and tool-name for a single-file edit

```bash
#!/usr/bin/env bash
set -euo pipefail

WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

# Trust the hook up front so the run measures the payload, not the trust prompt.
# The harness's own choice of file (codex.py:110) is hooks.json; probes use the
# same file so what's observed matches what lh deploy would actually write.
cat > "$CODEX_HOME/hooks.json" <<'JSON'
{
  "description": "codex-evidence probe — dumps every PreToolUse/PostToolUse payload",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'cat >> '\"$CODEX_HOME\"'/pre_tool_use.jsonl; echo'" } ] }
    ],
    "PostToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'cat >> '\"$CODEX_HOME\"'/post_tool_use.jsonl; echo'" } ] }
    ]
  }
}
JSON
# CODEX_HOME isn't expanded inside the JSON heredoc above the way the outer
# shell expands it — rewrite the two commands with the real path substituted so
# the sink is unambiguous regardless of how Codex invokes the handler's shell.
python3 - "$CODEX_HOME" <<'PY'
import json, sys
home = sys.argv[1]
p = f"{home}/hooks.json"
doc = json.load(open(p))
doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = f"/bin/sh -c 'cat >> {home}/pre_tool_use.jsonl; echo'"
doc["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = f"/bin/sh -c 'cat >> {home}/post_tool_use.jsonl; echo'"
json.dump(doc, open(p, "w"), indent=2)
PY

mkdir -p "$WORK"
cd "$WORK"
git init -q
printf 'first line\nsecond line\n' > target.txt
git add -A && git commit -q -m 'seed'

# --dangerously-bypass-hook-trust: this is a throwaway CODEX_HOME with nothing
# else in it, so there's no live trust state to protect and no interactive TUI
# to click through. Never pass this against a real ~/.codex.
codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit target.txt: change 'first line' to 'FIRST LINE'. Make exactly one edit, then stop." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "payloads: $CODEX_HOME/pre_tool_use.jsonl and post_tool_use.jsonl"
echo "target.txt after run:"; cat "$WORK/target.txt"
```

**Output files → evidence cells:**
- `$CODEX_HOME/pre_tool_use.jsonl` → §1 "Event envelope" and "`tool_input` shape
  for an edit" rows, and §2 "Native tool name for an edit" row.
- `$CODEX_HOME/post_tool_use.jsonl` → same rows, confirms the payload is stable
  across the two events.
- `$WORK/target.txt`'s final content → sanity check that the edit actually ran
  (if the hook sink works but the file is unchanged, something above is wrong
  in a way worth noting before trusting the rest).

### Probe 3 — multi-file edit in one turn

Same setup as Probe 1, second working tree, different prompt:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"
# ... same hooks.json as Probe 1 (copy it in, or point CODEX_HOME/hooks.json
# at a copy) ...

cd "$WORK"
git init -q
printf 'alpha\n' > a.txt
printf 'beta\n' > b.txt
git add -A && git commit -q -m 'seed'

codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit both a.txt (append 'ALPHA') and b.txt (append 'BETA') in the same turn." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "payloads: $CODEX_HOME/pre_tool_use.jsonl"
wc -l "$CODEX_HOME/pre_tool_use.jsonl"
```

**Output → evidence cell:** §2 "Multi-file edits in one call" — count the
`PreToolUse` records: one per file means one `ToolCall` per file (matches the
`Bash` shape), more than one field per record means a single call already
carries both paths.

### Probe 4 — deny an edit

Same setup, `hooks.json` swapped for one whose `PreToolUse` handler always
denies:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

cat > "$CODEX_HOME/hooks.json" <<'JSON'
{
  "description": "codex-evidence probe — always-deny PreToolUse",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'echo {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"codex-evidence probe: deny-all\"}}'" } ] }
    ]
  }
}
JSON

cd "$WORK"
git init -q
printf 'untouched\n' > target.txt
git add -A && git commit -q -m 'seed'

codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit target.txt: change 'untouched' to 'touched'." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "target.txt after a denied edit (must be unchanged if the deny worked):"
cat "$WORK/target.txt"
grep -i 'block\|den' "$CODEX_HOME/exec-transcript.jsonl" || echo "(no block/deny text found in transcript — paste the full transcript instead)"
```

**Output → evidence cell:** §3 "Refusal envelope, `PreToolUse`" — paste
`target.txt`'s final content (should read `untouched`) and the matching
transcript lines into that row.

**Ran 2026-09-16. Result: `target.txt` read `touched`, deny had no observed
effect.** This script's own bug is why: its `hooks.json` built the deny verdict
with a hand-escaped `echo {...}` one-liner and never captured the raw
`PreToolUse` payload, so there was no way to tell "hook fired, verdict ignored"
from "hook never fired." Probes 4b and 4c below fix both problems and
establish it was the former: a malformed envelope, Codex failing open exactly
as ADR-041 already documents for an invalid `permissionDecision` — not a
defect in the deny contract itself.

### Probe 4b — validated deny, with payload capture

Fixes probe 4's malformed verdict (hand-escaped `echo` → `json.dumps` via a
script file, no nested shell quoting) and adds a raw-payload capture running
*before* the verdict is emitted, so the run answers "did the hook fire" and
"was deny honoured" separately instead of conflating them into one absence.

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

# A standalone script file, referenced by bare path — not a `-c` one-liner.
# Probe 4's hand-escaped `echo {json}` is exactly the failure mode this
# sidesteps: no nested shell/python/JSON quoting to get wrong by hand.
cat > "$CODEX_HOME/deny_hook.py" <<PY
import sys, json
open("$CODEX_HOME/pre_tool_use.jsonl", "a").write(sys.stdin.read() + "\n")
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "codex-evidence probe 4b: deny-all, validated",
    }
}))
PY

cat > "$CODEX_HOME/hooks.json" <<JSON
{
  "description": "codex-evidence probe 4b — validated deny + payload capture",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "python3 $CODEX_HOME/deny_hook.py" } ] }
    ]
  }
}
JSON

mkdir -p "$WORK"
cd "$WORK"
git init -q
printf 'untouched\n' > target.txt
git add -A && git commit -q -m 'seed'

codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit target.txt: change 'untouched' to 'touched'." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "target.txt after a (validated) denied edit — must be 'untouched' if the deny worked:"
cat "$WORK/target.txt"
echo
echo "raw PreToolUse payloads captured BEFORE the deny verdict was emitted (one per line):"
cat "$CODEX_HOME/pre_tool_use.jsonl" 2>/dev/null || \
  echo "(file does not exist — the hook never fired for anything in this run, which is itself the answer to question (b))"
```

**Ran 2026-09-16. Result: `target.txt` stayed `untouched`; `pre_tool_use.jsonl`
recorded `tool_name: "Bash"`, `tool_input.command: "pwd; rg --files -g
AGENTS.md -g target.txt"`; the transcript logged `error=Command blocked by
PreToolUse hook: codex-evidence probe 4b: deny-all (validated envelope).
Command: pwd; rg --files ...`.** The deny worked. This confirms the original
probe's malformed envelope, not an unhooked path, explained the earlier
"touched" result — for the `Bash` path. Probe 4c below repeats this forcing a
native edit instead.

### Probe 4c — validated deny, forcing the native edit path

Same script as Probe 4b, with the prompt changed to steer the model away from
a shell heredoc and toward Codex's own patch tool: `"Use your native file-edit
tool (not a shell command) to change 'untouched' to 'touched' in target.txt."`
Everything else — the `deny_hook.py`, the `hooks.json`, the flags — is
identical to Probe 4b.

**Ran 2026-09-16. Result: `target.txt` stayed `untouched`; `pre_tool_use.jsonl`
recorded `tool_name: "apply_patch"`, `tool_input.command:` a raw patch blob
(`*** Begin Patch\n*** Update File: <abs path>/target.txt\n@@\n-untouched\n+touched\n*** End Patch`);
the transcript logged the same `Command blocked by PreToolUse hook` line,
echoing the patch blob as the blocked command.** The deny worked on the native
edit path too, and — the more important result — the native path **is**
gated by `PreToolUse`, firing with `tool_name: "apply_patch"`. The first
round's reading that it wasn't hooked is withdrawn; that round's deny envelope
was the same malformed one probe 4 used, so its "no block" observation never
distinguished "unhooked" from "hooked but the invalid verdict was ignored."
This run distinguishes them: hooked, and deny honoured once the verdict is
valid.

**Output → evidence cells:** §1 "`tool_input` shape for an edit" and
"`hook_event_name`", §2 "Native tool name for an edit", §3 "Refusal envelope"
— all closed by these two runs together, recorded above.

### Probes 5–8 — multi-file, delete spelling, read dialect, auth.json shape

Ran 2026-09-16 from an Aqua terminal (`probe5-7.sh`), against `codex-cli
0.154.0`, model `gpt-5.6-sol` — a different model than the six probes above
(`gpt-6-astra`); nothing below turned on the model, only on the binary. Same
fixture discipline as Probes 1-4c: a fresh, disposable `CODEX_HOME` per probe
with `auth.json` copied in and a `hooks.json` dumping every
`PreToolUse`/`PostToolUse` payload to `pre_tool_use.jsonl`; a fresh `WORK` dir
seeded with `a.txt='alpha'`, `b.txt='beta'`,
`target.txt='first line\nsecond line\nthird line'`; invoked as `codex exec
--dangerously-bypass-hook-trust --sandbox workspace-write
--skip-git-repo-check -C $WORK --json "<prompt>"`. Raw output kept at
`~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-harness/reports/codex-probes-5-8-output.txt`.

**Probe 5 — multi-file `apply_patch`.** Prompt: *"Use your built-in
file-editing tool (apply_patch), NOT the shell, to change 'alpha' to 'ALPHA'
in a.txt and 'beta' to 'BETA' in b.txt, in a single patch."*

```
#1 event=PreToolUse tool_name='apply_patch' tool_input_keys=['command']
   sections: ['*** Update File: <abs path>/a.txt', '*** Update File: <abs path>/b.txt']
   markers : ['*** Begin Patch', '*** End Patch']
files after: a.txt=ALPHA| b.txt=BETA| target.txt=first line|second line|third line|
```

One record, one blob, two `*** Update File:` sections — both files changed.
**Output → evidence cell:** §2 "Multi-file edits in one call", now resolved.

**Probe 6 — delete spelling.** Prompt: *"Use your built-in file-editing tool
(apply_patch), NOT the shell, to delete target.txt."*

```
#1 event=PreToolUse tool_name='apply_patch' tool_input_keys=['command']
   sections: ['*** Delete File: <abs path>/target.txt']
   markers : ['*** Begin Patch', '*** End Patch']
files after: a.txt=alpha| b.txt=beta| target.txt=<deleted>
```

One record, literal header `*** Delete File: <abs path>`, no diff body — the
file was removed from disk. **Output → evidence cell:** §2's new "Delete
spelling" row, above.

**Probe 7 — read dialect.** Prompt: *"Read target.txt and tell me its second
line. Do NOT use a shell command; use your built-in file-reading tool."*

```
#1 event=PreToolUse tool_name='list_mcp_resources' tool_input_keys=[]
assistant: "No built-in text-file reader is available in this session, so I
couldn't read `target.txt`. I did not use a shell command."
files after: unchanged
```

One `PreToolUse` record, `tool_name: list_mcp_resources`, empty `tool_input`,
then Codex gave up rather than fall back to `Bash` — 0.154.0 has no native
read tool. **Output → evidence cells:** §2's `pre-tool-use-read-size` row and
its ceiling note, above.

**Probe 8 — `~/.codex/auth.json` top-level shape** (keys and value types
only, no values):

```
{'auth_mode': 'str', 'OPENAI_API_KEY': 'NoneType', 'tokens': 'dict', 'last_refresh': 'str'}
```

La sub-forma de `tokens`, medida el 2026-09-16 desde una terminal Aqua
(`[run]`, claves y tipos, sin valores):

```
{'id_token': 'str', 'access_token': 'str', 'refresh_token': 'str', 'account_id': 'str'}
```

Con eso el archivo entero está en registro, y **no tiene campo de expiry en
ningún nivel**: el único marcador temporal es `last_refresh`. Eso cierra la
pregunta de `CodexAdapter.credentials_file()` (ADR-045 D4/A4) en negativo — el
`check_auth` del preflight deriva su veredicto de un expiry, así que apuntarle
el parser a este archivo sólo podría dar "unexpected shape". Derivar un
veredicto de la antigüedad de `last_refresh` es una heurística con su propio
umbral: decisión separada, con su propia probe (cuán viejo puede ser
`last_refresh` con el login todavía vivo).

**Probe 9 (keychain entry) ran on 2026-09-16 from an Aqua terminal, never from
an agent pane.** Without `-w`, it exposed the Claude Code item's metadata and
showed an `mdat` from the day of a successful login while the file mirror was
older. No secret value was printed. [ADR-058](../adrs/058-keychain-mdat-is-operator-only.md)
records why that useful operator evidence still must not become an automatic
hook call: an agent pane also descends from Aqua, so the required execution
boundary cannot be enforced by lazy-harness.

## Lo que el gate F8 ya midió y el evidence tiene que confirmar o falsificar

`specs/gates/f8/translation-gate.sh` runs entirely between two Python objects —
the shipped `ClaudeCodeAdapter` and the shipped `CodexAdapter` — and says so in
its own header (lines 88-106): *"the `codex` binary is never invoked, and the
payloads are written in Claude Code's dialect."* Concretely, its
`payload_for_operation` (line 352) feeds the *literal* Claude Code payload
`{"tool_name":"Edit","tool_input":{"file_path":"/f8/probe.py",...}}` to **both**
translators, including the one under `CodexAdapter`. That payload assumed the
exact fact this document's §2 has now confirmed is not what happens: Codex's
real wire `tool_name` for an edit is `"Bash"` **or** `"apply_patch"`, the
model's own non-deterministic choice, never `"Edit"`. The gate's own inputs
never exercised either real case — it measured "what happens if Codex sent
Claude's tool name," not "what Codex actually sends."

**Measured 2026-09-16, by reading the code, confirmed above in §2:**
`CodexAdapter._parse_tool` (`codex.py:178-191`) never populates `ToolCall.edits`
or `.reads` for *any* tool name — those fields default to `()` and nothing in
the method sets them. This is why the ADR's account needed correcting: the
`operation` gate is the *first* of two, not the only one. **Resolved against
the real binary, 2026-09-16, across two probe rounds**: Codex takes two
edit paths, `Bash` (most runs) and `apply_patch` (confirmed real and hooked
only once probe 4c used a validated deny — the first round's read of
`apply_patch` as unhooked was itself a malformed-envelope artefact, see §1/§3).
The two-guard analysis below covers both paths.

Per builtin, the two guards it actually hits under `CodexAdapter` today:

| Builtin | First guard | Result on `Bash` | Result on `apply_patch` | Second guard | Result |
|---|---|---|---|---|---|
| `post-tool-use-format` | `tool.operation is not Operation.MODIFY_FILE` (`post_tool_use_format.py:32`) | Fails: `operation` is `RUN_COMMAND`, never `MODIFY_FILE`. | Fails **today**: `operation` is `None` — `apply_patch` isn't in `_TOOL_OPERATIONS` at all. Mapping it to `MODIFY_FILE` would flip this guard to pass. | `for edit in tool.edits` (`post_tool_use_format.py:36`) | Never reached on either path today. If `apply_patch` were mapped, this becomes reachable and still fails: `tool.edits` is `()` regardless of `operation`, because `_parse_tool` never parses the patch blob (§2). |
| `pre-tool-use-read-size` | `tool.operation is not Operation.READ_FILE` (`pre_tool_use_read_size.py:105`) | Fails: `RUN_COMMAND`, never `READ_FILE`. | Fails: `None`, and would still fail even mapped — `apply_patch` is an edit, not a read; `READ_FILE` is the wrong target operation for it regardless. | `for path in tool.reads` (`pre_tool_use_read_size.py:119`) | Never reached, and mapping `apply_patch` doesn't change that — this hook was never going to apply to an edit tool. **Probe 7, 2026-09-16 (model `gpt-5.6-sol`): confirmed inert for a different reason than assumed.** Asked for a native read, Codex fired `PreToolUse` with `tool_name: list_mcp_resources`, empty `tool_input`, then told the model no built-in text-file reader is available in this session — 0.154.0 has no native read tool at all. Reads go through `Bash` (`cat`/`sed`/`rg`), the same structurally-ungateable path this document already records for edits. |
| `pre-tool-use-memory-size` | `tool.native_name not in INSPECTED_TOOLS` where `INSPECTED_TOOLS = {"Edit", "Write"}` (`pre_tool_use_memory_size.py:44,225`) | Fails: `native_name == "Bash"`, never in the set. | **Fails today, confirmed by run**: `native_name == "apply_patch"`, and `"apply_patch"` is not in `{"Edit","Write"}` either — the set itself needs widening, separately from `_TOOL_OPERATIONS`. | `for edit in tool.edits` (`pre_tool_use_memory_size.py:234`) | Never reached on either path today. If both the set *and* `_TOOL_OPERATIONS` were fixed, still fails: `tool.edits` stays `()` until the patch blob is parsed. |
| `post-tool-use-sync-claude` | Same `INSPECTED_TOOLS` check (`post_tool_use_sync_claude.py:32,76`) | Fails: `"Bash"` not in the set. | Fails: `"apply_patch"` not in the set. | `tuple(edit.path for edit in tool.edits)` (`post_tool_use_sync_claude.py:78`) | Never reached; same blob-parsing gap blocks it even if the set and the mapping were both fixed. |
| `post-tool-use-ansible-lint` | Same `INSPECTED_TOOLS` check (`post_tool_use_ansible_lint.py:33,113`) | Fails: `"Bash"` not in the set. | Fails: `"apply_patch"` not in the set. | `for edit in tool.edits` (`post_tool_use_ansible_lint.py:122`) | Never reached; same blob-parsing gap. |

**Corrected conclusion: two fixes are required, and neither alone is
sufficient — sharper, and more pessimistic, than the ADR's original "widening
`_TOOL_OPERATIONS` is a no-op."** That framing implied one missing mapping was
the whole defect. It isn't. Two independent gaps stack:

1. **`_TOOL_OPERATIONS` has no entry for `apply_patch`**, so it parses with
   `operation=None` today — necessary to fix for `post-tool-use-format` and
   `pre-tool-use-read-size` to even have a chance (and `pre-tool-use-read-size`
   still wouldn't apply, being about reads, not edits). `INSPECTED_TOOLS =
   {"Edit", "Write"}` separately has no entry for `"apply_patch"` either — a
   second, independent set that gates the other three builtins and needs its
   own widening.
2. **Even with both of those fixed, `_parse_tool` still never parses
   `apply_patch`'s `tool_input.command` into a `FileEdit`.** The value under
   `command` is patch *text* — `*** Begin Patch\n*** Update File: <path>\n@@\n...\n*** End Patch`
   — not a structured field. `tool.edits` stays `()` until something parses the
   `*** Update File: <path>` lines out of that blob. Mapping the operation and
   widening the tool-name set are both necessary and both insufficient on
   their own: every one of the five builtins gated on `tool.edits` needs the
   parser too.

**Correction, 2026-09-16, after #348.** Shipping the fixes above found one
more, absent from this reconciliation: `pre_tool_use_memory_size._projected_text`
branches on the *tool name* — `"Write"` takes `content`, `"Edit"` replays
`replacements`, anything else falls through to `None` and the hook goes quiet.
`apply_patch` carries both shapes in one blob, so it is the one tool whose
branch is chosen by the `FileEdit` it carries, not by its name. With
`_TOOL_OPERATIONS`, `INSPECTED_TOOLS` and the patch parser all in place, this
builtin still stayed silent — a fourth fix, not the three implied above.
Closed in #348; `specs/backlog.md` §Done has the record.

**`pre-tool-use-read-size`'s inertness is now a measured design limit, not an
open question.** Probe 7 (2026-09-16, model `gpt-5.6-sol`) asked Codex for a
native read and it fired `PreToolUse` with `tool_name: list_mcp_resources`,
empty `tool_input`, then answered that no built-in text-file reader is
available in this session. Codex 0.154.0 has no native read tool at all —
reads go through `Bash` (`cat`/`sed`/`rg`), the same tool this document
already records as structurally ungateable for edits. ADR-044 §2 left this
builtin un-widened on the assumption that `apply_patch` is an edit, not a
read; the deeper reason it stays inert is now on record — there is no read
dialect under Codex to gate, full stop.

**The `Bash` path is structurally different, not just currently unmapped: it
cannot be gated as an edit at all with information the hook has.** `tool_input`
for a `Bash`-mediated edit is `{"command": "<arbitrary shell script>"}` — there
is no reliable path to extract, because the model can construct that script
however it likes (the observed heredoc is one shape among unbounded others).
Mapping `Bash` to `MODIFY_FILE` when its `command` merely *happens* to write a
file would be wrong for the same reason `RUN_COMMAND` is the correct
`operation` for it today: from the hook's point of view a `Bash` call is a
command, not a structured edit, regardless of what that command does. **Net
effect for the harness**: Codex's model chooses non-deterministically between
an edit path that's parseable in principle (`apply_patch`, pending the two
fixes above) and one that structurally isn't (`Bash`). Even a fully-fixed
adapter would only gate half of Codex's edits — the other half arrives as an
opaque shell command indistinguishable, at the hook layer, from any other
`Bash` call.

**This sharpens the F8 gate's own finding rather than reversing it.**
`translation-gate.sh` feeds every translator the literal payload
`{"tool_name":"Edit",...}` (line 352) — Claude Code's dialect, neither of
Codex's two real ones. Under that synthetic input, the `INSPECTED_TOOLS` check
*passes* (the gate told the Codex translator the tool was called `"Edit"`), so
the gate's inert verdict for those three builtins is produced entirely by the
second guard, `tool.edits` being empty, exactly as its own comments say.
Against the real binary the verdict is the same — inert — but for a guard
combination the gate's synthetic payload never exercised: the real `apply_patch`
payload fails at *both* guards today (tool-name set, then blob parsing), and
the real `Bash` payload was never a candidate for gating as an edit regardless
of either guard. F8's header names this precisely: it measures "the shipped
adapter pair," two Python objects, and explicitly disclaims knowing anything
about the binary. That isn't a defect in F8 — it's the exact gap this document
exists to close, and it's now closed with a sharper, two-part diagnosis than
either F8 or the original ADR account gave.

## Corrección al design doc padre

`specs/designs/2026-09-13-multi-agent-harness-design.md`'s provider table
(line 1196) listed Codex's native tool names as `apply_patch, shell (source)`
— both tagged as read off source, never run. Both are now confirmed real
by run, elevated from `(source)` to `(run, 0.154.0)`: Codex takes both paths,
the model's own non-deterministic choice, and both fire `PreToolUse` (`Bash`
with `tool_name: "Bash"`, `apply_patch` with `tool_name: "apply_patch"` and a
raw patch-text blob under `tool_input.command`). The design doc's own
claims-correction table (lines 90-97, "Where the convergence stops") is where
this repo records exactly this kind of update; the row added there for this
document is updated in place to reflect the corrected, two-path finding rather
than the first round's now-withdrawn "`file_change` looked unhooked" reading,
and the provider table's Codex cell is updated the same way. Nothing else in
that document is touched — the architecture decisions built on "plural
`edits`/`reads` because an edit can touch several files" (line 1009) still
hold: probe 3 confirms multi-file edits happen in one hook call for `Bash`,
and nothing here contradicts the same being possible for `apply_patch`
(untested, §2).

**Update, probe 5 (2026-09-16, above): the "untested" just above is now
resolved.** `apply_patch` concatenates a multi-file edit into one blob with
multiple `*** Update File:` sections rather than splitting across hook calls —
confirmed in §2's "Multi-file edits in one call" row.

**A third tool_name surfaced, outside the two-path pair above.** Probe 7
(§2's `pre-tool-use-read-size` row, below) fired `PreToolUse` with
`tool_name: list_mcp_resources` and an empty `tool_input` (`{}`) when asked
for a native read — not an edit tool, and not added to the provider table's
edit-path list, but the concrete evidence behind "Codex has no native read
tool at 0.154.0."

## 5. Rollout format (transcript on disk)

**Medido** el 2026-09-16 sobre los rollouts que `codex-cli 0.154.0` escribió en
esta máquina: 15 archivos, 1.147 líneas, 0 no parseables, todos con
`session_meta.cli_version == "0.154.0"`. `[log], 0.154.0` — leídos del disco, no
corridos contra el binario. Un schema de transcript vale sólo para la versión en
la que se observó (design doc `:1901-1905`), así que la versión queda anotada acá
y en el docstring del reader, y **no** hay switch de versiones: nunca existió una
segunda.

Nada del contenido de esas sesiones entra al repo. Lo que sigue es forma —
claves, anidamiento, tipos, inventario de kinds y conteos. Los fixtures de
`tests/unit/test_agent_codex_transcript.py` son sintéticos, reconstruidos desde
esta tabla.

### 5.1 Envelope

Una línea = un objeto JSON con exactamente cuatro claves, en 416/416 líneas del
día medido:

| Clave | Tipo | Observado |
|---|---|---|
| `timestamp` | `str` | ISO-8601 UTC con milisegundos y sufijo `Z`: `2026-09-16T12:02:13.926Z` (24 chars). `datetime.fromisoformat` lo acepta desde 3.11. |
| `type` | `str` | El kind de nivel superior — seis valores, tabla 5.2. |
| `payload` | `dict` | El cuerpo. Para `event_msg` y `response_item` lleva su propio `payload.type`; para los otros cuatro, no. |
| `ordinal` | `int` | Índice creciente dentro del archivo. |

**Ruta y nombre:** `$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<YYYY-MM-DD>T<HH-MM-SS>-<uuid v7>.jsonl`.
El stamp del nombre es el **arranque de la sesión en hora local, sin offset**:
`rollout-2026-09-16T09-02-04-...` cuya primera línea es
`2026-09-16T12:02:13.926Z` — tres horas de diferencia en un host UTC-3. No es
hora de modificación ni UTC; ver ADR-048 para por qué `locate_sessions` filtra
por mtime y no por el nombre.

### 5.2 Inventario de kinds

Los 15 archivos, `type` (+ `payload.type` donde existe):

| Kind | Líneas | Señal que entrega | Leído |
|---|---|---|---|
| `event_msg/item_completed` | 441 | — (duplica lo de abajo) | no |
| `event_msg/token_count` | 179 | duplica `token_usage_record` | no |
| `token_usage_record` | 176 | `TOKEN_USAGE` | **sí** |
| `response_item/custom_tool_call` | 154 | `TOOL_CALLS` | **sí** |
| `response_item/custom_tool_call_output` | 154 | — (resultado, no llamada) | no |
| `response_item/message` | 151 | `MESSAGES` (roles `user`/`assistant`) | **sí** |
| `response_item/reasoning` | 134 | — (`encrypted_content`, no es texto que alguien vio) | no |
| `event_msg/task_started` | 23 | — | no |
| `event_msg/task_complete` | 23 | — | no |
| `turn_context` | 23 | — (aporta `model`, ver 5.3) | **sí** |
| `world_state` | 18 | — (instrucciones compuestas del turno) | no |
| `session_meta` | 15 | — (`cli_version`, `cwd`, `git`, `id`) | no |
| `event_msg/thread_settings_applied` | 8 | — | no |
| `response_item/function_call` | 2 | `TOOL_CALLS` | **sí** |
| `response_item/function_call_output` | 2 | — | no |

**No hay ningún kind, ni ningún campo de payload, que marque un objetivo
explícito.** Codex 0.154.0 no tiene `/goal` y el rollout no lleva nada
equivalente: `GOAL_STATUS` no se entrega, y `signals()` no lo declara.

### 5.3 Lo que se lee: tres señales y un campo

**`response_item/message`** — `{type, id, role, content[], phase?, internal_chat_message_metadata_passthrough}`.
`role` ∈ `{assistant: 67, developer: 46, user: 38}`. `content[]` son bloques
`{type, text}` con `type` ∈ `{input_text: 135, output_text: 67}` — `input_text`
en turnos `user`/`developer`, `output_text` en `assistant`. No hay string pelado
en `content` (a diferencia de Claude Code). `developer` es el canal de
instrucciones compuestas, no un turno de nadie: no se emite (ADR-048).

**`response_item/custom_tool_call`** — `{type, id, call_id, name, input, status}`.
`name` == `exec` en 154/154 llamadas. `status` == `completed`. **`input` es un
`str` que no es JSON y no es shell**: 154/154 multilínea, 154/154 contienen
`await `, 154/154 contienen `;`, 70 contienen `const `; primeras palabras
`text` (81), `const` (64), `for` (6), `await` (3). Es un programa para el
runtime de celdas de Codex (`unified_exec`), no un comando. Por eso no se mapea
a `ToolCall.command` (ADR-048).

**`response_item/function_call`** — `{type, id, call_id, name, arguments}`.
`name` == `wait` en 2/2; `arguments` sí es JSON, con claves
`{cell_id, max_tokens, yield_time_ms}` — el otro extremo del mismo runtime de
celdas.

**`turn_context`** — `{cwd, model, approval_policy, approvals_reviewer, sandbox_policy, file_system_sandbox_policy, permission_profile, active_permission_profile, collaboration_mode, personality, effort, summary, timezone, current_date, realtime_active, multi_agent_version, comp_hash, turn_id, root_turn_id, workspace_roots}`.
Se lee **un solo campo: `model`** (`str` no vacío en 23/23 líneas, un único
modelo distinto por archivo en 15/15). Es el único kind del rollout que nombra
el modelo, y está en una línea distinta de la que reporta los tokens: el reader
arrastra el último declarado hacia adelante, sobre los eventos que le siguen
(`_turn_context_model`). En los 15 archivos medidos, **los 176
`token_usage_record` vienen después de algún `turn_context`** — igual el reader
deja el modelo en `None` si no lo hubo, porque un archivo truncado o rotado es
exactamente donde aparecería. No viola ADR-048: `turn_context` no duplica
ninguna señal, y el resto de su payload no se emite.

**`token_usage_record`** — `{session_id, thread_id, turn_id, root_turn_id, response_id, usage, turn_token_usage, thread_token_usage}`.
Los tres objetos de usage tienen forma idéntica:
`{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens}`, todos `int`. `usage` y
`turn_token_usage` fueron iguales en cada línea medida; `thread_token_usage` es
el acumulado de la sesión. Mapeo a `TokenUsage`:
`input_tokens→input_tokens`, `output_tokens→output_tokens`,
`cached_input_tokens→cache_read_tokens`,
`cache_write_input_tokens→cache_creation_tokens`.
`reasoning_output_tokens` y `total_tokens` no tienen campo y no se suman a
ninguno.

`response_id` → `message_id`, y es la clave de dedup: `str` en 176/176 y
**único across los 15 archivos**, mientras que esos mismos 176 comparten 21
`turn_id` — deduplicar por turno tiraría todos los usage records de un turno
menos el primero. **`response_id` no aparece en el stream `response_item`**: 0
de 176 coinciden con el `id` de un item, así que los dos streams no se joinean
por ahí y el record se banca solo. `cache_creation_1h_tokens` queda `None`:
Codex reporta una sola escritura de caché, sin split por TTL.

### 5.4 Lo que el stream `event_msg` duplica

`event_msg/item_completed` lleva `{completed_at_ms, started_at_ms, thread_id, turn_id, item}`
y `item.type` ∈ `{CommandExecution: 211, Reasoning, AgentMessage, UserMessage, Extension, FileChange}`.
Es la vista de la TUI del mismo turno que el stream `response_item` ya registró,
y no lleva `call_id`. Se descarta entero para no contar dos veces (ADR-048).

`item.type == "CommandExecution"` es igualmente la **única** grafía donde aparece
el comando realmente ejecutado: `command` es una lista de 3 elementos, siempre
`["/bin/zsh", "-lc", "<script>"]`, con `cwd`, `exit_code`, `status`
(`completed: 193`, `failed: 18`), `duration{secs,nanos}`, `process_id` y
`parsed_cmd[]` (tipos `read: 231`, `unknown: 129`, `search: 58`,
`list_files: 12`). `source` == `unified_exec_startup` en 211/211.

### 5.5 Lo que no se observó, y por lo tanto no se declara

- **`apply_patch` como tool call del rollout: 0 ocurrencias** en 154 llamadas y
  15 sesiones. En este modo las ediciones las hace el programa `exec`, y la
  única línea que nombra los archivos tocados es
  `item_completed/FileChange` (3 ocurrencias), cuyo `changes` es un dict
  **tecleado por path absoluto** → `{type, content}`. No se emite: no tiene
  `call_id`, pertenece al stream duplicado, y `_parse_patch` no tiene entrada
  acá. El día que un rollout traiga un `custom_tool_call` llamado
  `apply_patch`, el mapeo a `{"command": input}` es una línea y un test.
- **Un segundo `cli_version`.** 15/15 archivos dicen `0.154.0`.
- **`GOAL_STATUS`**, por 5.2.

## 6. Acceptance run

El criterio de éxito de la iteración, escrito como script:
`specs/gates/f9/codex-acceptance.sh`. **Corrió cuatro veces**; la cuarta
(2026-09-18 08:27) es la que cerró la iteración y §6.4 la registra entera.

El gate lo corre el usuario desde una terminal Aqua, contra un `lh` instalado y
el profile `lazy-codex` (`config_dir = ~/.codex-lazy`, `agent = "codex"`):

```bash
specs/gates/f9/codex-acceptance.sh lazy-codex
```

`--dry-run` imprime cada comando con los placeholders sustituidos y no ejecuta
ninguno; es el único modo que corre en CI y en un pane de agente, y es lo que
cubre `tests/integration/test_f9_gate_dry_run.py`.

Códigos de salida: `0` PASS, `1` FAIL (el gate corrió y el sistema no lo
satisfizo), `2` HARNESS ERROR (el gate no pudo correr y no midió nada), `3`
BLOCKED (el gate corrió y algo de lo que depende todavía no está embarcado, así
que la aserción nunca se alcanzó). La distinción es el punto: un `2` nunca es
evidencia sobre el sistema, y un `3` no puede archivarse como criterio cumplido
—por eso no sale 0—.

Run log — el detalle de las cuatro está en §6.4:
- 2026-09-17 una corrida previa se cortó en el preflight: la búsqueda de
  intérprete no seguía el symlink de `lh`; arreglado en #371.
- 2026-09-17 09:52 — FAIL 4 · BLOCKED 1 · NO-OBS 1 (`lh` 0.71.0).
- 2026-09-17 12:25 — FAIL 4; el paso manual de aprobación se salteó.
- 2026-09-17 12:32 — FAIL 3; causa cerrada por el probe 6 (§4.2).
- 2026-09-18 08:27 — **17 aserciones, 0 failed, 0 blocked, 2 not observed**.

### 6.1 Fases y observaciones esperadas

| # | Fase | Aserción | Esperado | Observado |
|---|---|---|---|---|
| A1 | untrusted | `lh doctor` tras `lh deploy` | reporta hooks `untrusted` | `ok` |
| A2 | untrusted | fixture de deny por `Bash` | el comando **corre**: hooks sin trust no disparan | `ok` — `never-invoked`, y el delete corrió |
| B1 | trusted | `lh doctor` tras aprobar en la TUI | ningún hook `untrusted`; quedan en `unknown` | `ok` — quedan `unknown` |
| B2 | trusted | mismo fixture `Bash` | **bloqueado**; el stream trae `Command blocked by PreToolUse hook` | NO-OBS en la corrida; la relectura de §6.4 lo lee `honoured` |
| B3 | trusted | `apply_patch` sobre `.env` | **bloqueado**; el archivo queda intacto en disco | `ok` — bloqueado, `.env` intacto |
| B4 | trusted | turno benigno completo | corre `session_stop`, queda rollout | `ok` |
| B5 | trusted | `lh metrics ingest` | **al menos una** fila `session_stats` con `agent = "codex"` para el profile (ADR-053) | `ok` — 10 filas `agent=codex` |
| B6 | trusted | `lh run --bypass=enable` | **error** — ADR-049 no mapea `enable` en Codex | `ok` |
| B7 | trusted | `lh run --bypass=activate --dry-run` | el argv trae `--approve-for-me` | `ok` |
| B8 | trusted | `lh run … -- exec …` real | `launches` suma una fila `agent=codex`, `entry=run` | `ok` |
| C1 | reapproval | declaración cambiada + redeploy | `lh doctor` reporta `trust stale` (#367); `orphaned` y/o `untrusted` si el `lh` instalado es anterior a #367 | `ok` — `trust stale` |

Las aserciones de stream valen **sólo para la versión en que se observaron**.
El preflight imprime `codex --version` y avisa — sin fallar — si difiere de
`0.154.0`; esa versión va pegada junto a la tabla.

### 6.2 Tres correcciones que el gate encontró al escribirse

Medidas sobre `origin/main` en `ce86cb3`. Contradicen el brief que encargó el
gate; el repo gana.

1. **Actualizado 2026-09-16 (release-gate-071): `trust stale` se shippeó en
   #367.** Esta corrección decía "no hay veredicto `stale`, y no va a haberlo"
   — cierto contra `ce86cb3`, falso desde #367. Lo que no cambió:
   `agents/codex_trust.py` sigue sin recomputar el `current_hash` de Codex —lo
   único que distinguiría `Trusted` de `Modified` en los términos del propio
   Codex— porque eso es reimplementar su normalización TOML y su hash de
   versión, silenciosamente mal ante cualquier cambio de Codex. `stale` no es
   eso: es una señal del lado del harness, `lh doctor` compara la declaración
   actual contra la copia pre-deploy que `deploy/snapshot.py` ya guarda en su
   manifest (`TRUST_STALE_VERDICT`, `agents/codex_trust.py`). La trust key
   sigue llevando la **posición** del grupo y del handler
   (`agents/codex.py:458-472`), y eso sigue siendo lo que arma `orphaned` y
   `untrusted` — quedan como alternativa para un `lh` instalado antes de #367,
   nunca como primera opción. La fase C ahora afirma `trust stale` primero.
2. **Medir Codex es el punto de B5, y ADR-051 está siendo superseded.** ADR-051
   se negó a medir Codex porque `TranscriptEvent` no lleva modelo, ni message id,
   ni el split de cache de 1 hora, y `session_stats` es `UNIQUE(session, model)`.
   Su propia sección "What would change the decision" nombra el arreglo —un
   cambio de Protocol en `agents/base.py`— y se abstiene de hacerlo ahí.
   **ADR-053 hace exactamente ese cambio** y supersede a ADR-051. Así que el
   criterio es el que el diseño siempre dijo: `lh metrics ingest` registra filas
   con `agent = "codex"`.
   B5 pasa con **al menos una** fila; cero filas es `BLOCKED BY ADR-053` —el `lh`
   instalado es anterior a la lane que lo implementa— y cuenta como gap, **nunca**
   como PASS. La columna `agent` ya existe desde ADR-050 (#364),
   `monitoring/db.py:74`, así que lo único que falta son las filas.
3. **`lh run` y `lh exec` cuentan launch los dos.** `record_launch` tiene dos
   call sites: `cli/run_cmd.py:129` con `entry="run"` y `cli/exec_cmd.py:408`
   con `entry="exec"`. Un borrador anterior de esta sección decía que `lh exec`
   no tenía ninguno; salió de un grep truncado y se retira. B8 sigue usando
   `lh run` porque es el passthrough bajo prueba y el launch que cuenta es
   `entry="run"`. Un `--dry-run` retorna antes de los dos call sites y no
   registra nada, por diseño.

### 6.3 Dependencias

- **B3 (trust de Codex) ya está en `main`**: `agents/codex_trust.py` y la
  sección `Codex hook trust` de `lh doctor` existen, así que A1, B1 y C1 tienen
  contra qué correr. Lo único que el gate no asume es la línea de re-trust en la
  salida de `lh deploy`: la afirma si está y la reporta si no.
- **B4 bloquea B5.** La lane B4 está implementando ADR-053, que supersede a
  ADR-051 haciendo el cambio de Protocol que 051 declinó —modelo, message id y
  split de 1 hora sobre `TranscriptEvent` / `TokenUsage`—. Hasta que eso llegue
  al `lh` instalado, `ingest_profile` sigue devolviendo un reporte vacío para
  todo agente que no sea `claude-code` (`monitoring/ingest.py:145-146`) y B5
  reporta `BLOCKED BY ADR-053`. El gate sale **3** en ese caso: no es PASS, no
  es FAIL, y no puede archivarse como criterio cumplido.
- **Afordancia de CLI que falta:** `lh doctor` no acepta `--json`
  (`cli/doctor_cmd.py:750-751` no declara opciones), así que A1, B1 y C1 se
  resuelven con `grep` sobre texto renderizado. Un `--json` de la sección de
  trust haría esas tres aserciones estructurales en vez de textuales.
- **Lo único que el gate no puede cerrar desde el repo:** si el `codex`
  top-level acepta `--approve-for-me` **antes** del subcomando `exec`. §7.1 lo
  midió sobre `codex exec`; la nota de límite de §7.4 dice que la transferencia
  al comando top-level es `[help]`, no `[run]`. B7 imprime el argv resuelto para
  que un fallo de parseo en B8 sea legible.

### 6.4 Las cuatro corridas

Preflight de la cuarta, tal como lo imprimió:

```
lh:    lazy-harness, version 0.71.1  (needs >= 0.71.0, which carries ADR-049/050/051)
codex: codex-cli 0.154.0  (evidence was measured on 0.154.0)
```

| corrida | `lh` | resultado |
|---|---|---|
| 2026-09-17 09:52 | 0.71.0 | FAIL 4 · BLOCKED 1 · NO-OBS 1 |
| 2026-09-17 12:25 | 0.71.0 | FAIL 4 — el paso manual de aprobación se salteó, así que la fase B midió hooks sin trust |
| 2026-09-17 12:32 | 0.71.0 | FAIL 3 — causa cerrada por el probe 6 (§4.2): el guard fue invocado y contestó `allow` a la grafía que el modelo eligió; trust nunca fue el delta |
| 2026-09-18 08:27 | 0.71.1 | **0 failed · 0 blocked · 2 not observed** |

Tabla de veredictos de la cuarta, pegada como salió:

```
  VERDICT  ASSERTION
  -------  ---------
  ok       codex is the version the evidence was measured on
  ok       profile 'lazy-codex' resolves through the Codex adapter
  ok       Bash fixture is denied end to end through the 'lazy-codex' adapter: Recursive delete (filesystem)
  ok       an apply_patch blob touching the fixture path is denied end to end too
  ok       doctor reports the deployed Codex hooks untrusted
  ok       untrusted hooks did not fire: the guard recorded no dispatch this turn and the recursive delete really ran [never-invoked]
  ok       no hook is reported untrusted any more
  NO-OBS   the Bash deny path was not exercised: permitted-spelling [denied]
  NO-OBS   the Bash deny path was not exercised: no-command [denied]
  ok       the native edit path is gated too: apply_patch onto a denied path was blocked [denied]
  ok       the denied file is unchanged on disk
  ok       a benign turn ran to completion, so session_stop fired and a rollout exists
  ok       ingest exit 0; session_stats rows for agent=codex on 'lazy-codex': 10 — the iteration's metering criterion is met
  ok       --bypass=enable is refused on Codex, as ADR-049 requires
  ok       activate expands through the adapter to the flag ADR-049 recorded
  ok       lh run recorded a launch with agent=codex, entry=run
  ok       doctor reports untrusted hooks again after the declaration changed

  assertions: 17 — 0 failed, 0 blocked, 2 not observed
```

Inventario de kinds por turno — claves y tipos, sin valores:

```
a-deny
    item.completed/agent_message  x2  {id:str, text:str, type:str}
    thread.started  x1  {thread_id:str, type:str}
    turn.started  x1  {type:str}
    item.started/command_execution  x1  {aggregated_output:str, command:str, exit_code:NoneType, id:str, status:str, type:str}
    item.completed/command_execution  x1  {aggregated_output:str, command:str, exit_code:int, id:str, status:str, type:str}
    turn.completed  x1  {type:str, usage:dict}

b-deny-bash
    item.completed/agent_message  x2  {id:str, text:str, type:str}
    thread.started  x1  {thread_id:str, type:str}
    turn.started  x1  {type:str}
    item.started/command_execution  x1  {aggregated_output:str, command:str, exit_code:NoneType, id:str, status:str, type:str}
    item.completed/command_execution  x1  {aggregated_output:str, command:str, exit_code:int, id:str, status:str, type:str}
    turn.completed  x1  {type:str, usage:dict}

b-deny-bash-pinned
    item.completed/agent_message  x2  {id:str, text:str, type:str}
    thread.started  x1  {thread_id:str, type:str}
    turn.started  x1  {type:str}
    turn.completed  x1  {type:str, usage:dict}

b-deny-patch
    item.completed/agent_message  x2  {id:str, text:str, type:str}
    thread.started  x1  {thread_id:str, type:str}
    turn.started  x1  {type:str}
    turn.completed  x1  {type:str, usage:dict}
```

#### Los dos NO-OBS eran huecos del instrumento, no conducta de Codex

Las dos aserciones no observadas caen las dos sobre el arm de `Bash`, y ninguna
dice nada sobre Codex. Los deltas de `hooks.log` de esos mismos dos turnos —
`blocks 11 -> 12` y `blocks 12 -> 13` — dicen que el guard **denegó** en los dos,
y `doomed/` sobrevivió al turno fijado. Lo que falló fue la lectura.

**Hecho 1 — la fase A borra el fixture y nada lo repone antes de la fase B.**
`mkdir -p "$DOOMED"` corría en el preflight y, la segunda vez, sólo antes del
re-prompt fijado. La fase A usa el mismo prompt de borrado recursivo y, con los
hooks sin trust, **corre**: run 4 lo midió (`never-invoked`, directorio borrado).
Así que el primer turno de deny de la fase B arrancó contra un fixture ausente,
`[ -d "$DOOMED" ]` leyó falso y el efecto se registró como `gone` sobre un turno
donde nadie borró nada. La lectura ya era incorrecta antes de que el turno
empezara. El gate ahora repone los dos fixtures entre fases y **imprime** lo que
repuso (`reseed_fixtures`).

**Hecho 2 — Codex no emite `command_execution` para un comando que su hook
`PreToolUse` bloqueó.** El inventario de kinds de `b-deny-bash-pinned` de arriba
es la medición: dos `agent_message`, los marcadores de turno, y nada más — el
modelo emitió el borrado fijado, el hook lo denegó (`blocks 12 -> 13`) y
`doomed/` sobrevivió. El probe 5 vio la misma forma (§4.1). El único registro del
comando es la línea de rechazo que escribe el propio Codex:

```
<ts> ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: <la razón del guard>. Command: <el comando>
```

**Dónde aterriza esa línea, medido sobre esta corrida.** El probe 5 la encontró
en `stderr`, y grepear `Command blocked` sobre el `tee` de la corrida entera no
devuelve nada —
pero está en los tres streams de deny de la corrida. `codex_turn` redirige el
turno entero con `> "$out" 2>&1`, así que el stderr de Codex **queda en el mismo
`stream-<label>.jsonl`**, intercalado entre filas JSON, y nunca llega al `tee`.
Las dos afirmaciones que parecían contradecirse —`stream_shows_block()` grepea
el stream, el probe 5 dice stderr— son la misma.

La razón la escribe el guard, así que ocupa cuatro líneas físicas y el comando
**no está en la línea que trae el marcador**: nada orientado a líneas lo
encuentra. `guard_contract.blocked_commands` lee la región desde el marcador
hasta la próxima fila que parsea como JSON, y toma la cola de `. Command: `.

Con los dos hechos cerrados, los mismos bytes de la corrida se releen así —
`guard_contract.py judge --profile lazy-codex --stream <artefacto> --effect
survived`, contra el profile desplegado:

| turno | comando recuperado | fuente | guard | veredicto |
|---|---|---|---|---|
| `b-deny-bash` | `rm -rf -- ./doomed` | `block-line` | `deny` | `honoured` |
| `b-deny-bash-pinned` | `rm -rf doomed` | `block-line` | `deny` | `honoured` |

Los dos NO-OBS cierran sobre la evidencia grabada, sin una quinta corrida.

**Un turno puede traer los dos.** `b-deny-bash` corrió un borrado que el hook
rechazó y después una inspección de sólo lectura que permitió. El comando del
contrato es el rechazado; `commands[-1]` tomaba la inspección, la repetía contra
el guard, sacaba `allow` y reportaba `permitted-spelling` sobre un turno donde el
guard denegó y Codex obedeció. La excepción es cuando el efecto **sí** ocurrió y
además corrió un comando permitido: ahí nada atribuye el borrado a uno o al otro,
y `ignored` es la única acusación de defecto que el contrato puede hacer, así que
el turno degrada al arm inconcluso y se vuelve a preguntar una vez.

## 7. Bypass levels

Medido el 2026-09-16 con `specs/gates/probes/codex-bypass-probe.sh` contra
`codex-cli 0.154.0`, desde una terminal Aqua. Fixture: un prompt que pide
escribir un marker en **dos** destinos fuera del workspace — uno bajo `$HOME`
(el estricto) y otro bajo un temp dir (el control, porque Seatbelt permite
escrituras ahí bajo `workspace-write`). Un solo destino habría leído
`--approve-for-me` como bypass completo.

`baseline` es control, no fila: escribió en ninguno de los dos, así que había
sandbox que evadir y el resto de las filas significa algo.

### 7.1 Phase 0 — qué acepta el parser de `codex exec`

| flags | resultado | evidencia |
|---|---|---|
| *(ninguno)* | aceptado | `[run]` |
| `-a never` | **RECHAZADO** — `error: unexpected argument '-a' found` | `[run]` |
| `-c approval_policy="never"` | aceptado | `[run]` |
| `--approve-for-me` | aceptado | `[run]` |
| `-s danger-full-access` | aceptado | `[run]` |
| `-c approval_policy="never" -s danger-full-access` | aceptado | `[run]` |
| `--dangerously-bypass-approvals-and-sandbox` | aceptado | `[run]` |

`-a/--ask-for-approval` existe **solo en el comando top-level**; `codex exec` lo
rechaza. `--full-auto` no existe en esta versión en ningún nivel (`[help]`).

### 7.2 Phase 1 — qué permite cada nivel

`exit` fue `0` en las seis corridas. Ninguna emitió señales de `approval` ni de
`sandbox`: el stream de 0.154.0 no tiene un kind para ninguna de las dos cosas,
de modo que **el sistema de archivos es la única verdad de terreno** acá — un
hallazgo sobre el stream, no sobre el bypass.

| candidato | flags | corrió comando | `$HOME` | temp | evidencia |
|---|---|---|---|---|---|
| `baseline` | *(ninguno)* | no | no | no | `[run]` |
| `approval-never-config` | `-c approval_policy="never"` | no | no | no | `[run]` |
| `approve-for-me` | `--approve-for-me` | **sí** | no | **sí** | `[run]` |
| `sandbox-danger` | `-s danger-full-access` | sí | **sí** | sí | `[run]` |
| `never-plus-danger` | `-c approval_policy="never" -s danger-full-access` | sí | **sí** | sí | `[run]` |
| `bypass-all` | `--dangerously-bypass-approvals-and-sandbox` | sí | **sí** | sí | `[run]` |

"corrió comando" se lee del stream: las corridas sin comando sólo traen
`item.completed` con `text`; las que corrieron traen `item.started` /
`item.completed` con `command`, `exit_code` y `status`.

### 7.3 Inventario de kinds observado

Envelope **plano** (`{"type": ...}`), no el anidado `{"id", "msg"}`. Kinds:
`thread.started` (`thread_id`), `turn.started`, `item.started`, `item.completed`
(`item.{id, type, text?, command?, aggregated_output?, exit_code?, status?}`),
`turn.completed` (`usage.{input_tokens, cached_input_tokens,
cache_write_input_tokens, output_tokens, reasoning_output_tokens}`).

### 7.4 Lo que esto decide

- **ENABLE → `None`.** Ningún candidato deja el bypass *disponible pero
  apagado*. `baseline` y `approval_policy="never"` son indistinguibles entre sí
  — ninguno corrió comando — y `--approve-for-me` ya corrió uno. No hay
  equivalente del `--allow-dangerously-skip-permissions` de Claude Code.
- **ACTIVATE → `--approve-for-me`.** Corrió el comando y el sandbox siguió
  rechazando la escritura fuera del workspace. Es "contestado sin vos", no
  "concedido siempre": rutea los approvals por revisión automática.
- **NO_SANDBOX → `--dangerously-bypass-approvals-and-sandbox`.** Las dos
  mitades en un flag. `-s danger-full-access` solo también llegó a `$HOME`, y
  **no** es el mapeo: saca el sandbox dejando la approval policy en su default,
  así que en el lanzamiento interactivo que `lh run` hace sacaría el sandbox y
  seguiría preguntando.
- **Los tres niveles no colapsan.** ACTIVATE y NO_SANDBOX son flags distintos y
  observablemente distintos, así que ninguno es alias del otro.

**Límite de la evidencia, cerrado el 2026-09-17:** la probe maneja `codex exec`
porque es lo medible sin interacción, mientras que `lh run` ejecuta el `codex`
top-level. Los dos flags del mapeo están en ambos comandos, así que la
transferencia era `[help]` aunque la conducta fuese `[run]`.

La acceptance run la movió a `[run]`. El lanzamiento real de B8 fue
`codex --approve-for-me exec --json <prompt>` — el argv que arma
`run_cmd.py` como `[argv0, *bypass_args, *args]` — y su stream trajo
`thread.started`, un `turn.completed` con 17261 input tokens y un
`agent_message` con el texto pedido. clap lo parseó: el `codex` top-level
acepta el flag **antes** del subcomando, así que la posición del bypass no
necesita ser por adapter. El `[help]` de esta nota era un límite de lo medido,
no una negativa del parser.

**Una cuarta bandera, solo `[help]`:** `codex exec --help` sobre 0.154.0
declara también `--dangerously-bypass-hook-trust` — *"Run enabled hooks without
requiring persisted hook trust for this invocation. DANGEROUS."*. No está
medida y **no** entra en `bypass_argv`: los tres niveles de ADR-049 son sobre
approvals y sandbox, y esto es sobre trust de hooks, que es una cuarta cosa.
Queda anotada porque es la única vía que el binario declara para ejercitar
hooks sin la aprobación manual en la TUI, y por lo tanto es lo primero que
alguien va a querer usar para automatizar el gate — decidirlo pide una medición
y una entrada de backlog, no una inferencia desde el `--help`.

## 8. Exit 2 as a refusal channel

Measured 2026-09-24 12:43 (-03) against `codex-cli 0.155.1`, model `gpt-6-sol`,
from an agent pane, with `CODEX_HOME=~/.codex-lazy` — the real profile and its
own `auth.json`, nothing copied out of it. The question: #460 made the
unknown-`--profile` fallback refuse a Codex caller that has no Codex profile to
fall back to, and that refusal is the runner's blocking-failure row — exit 2,
nothing on stdout, the reason on stderr. §3 had only ever measured the JSON
`deny` envelope on exit 0; Codex's exit-code path had never been run, so the
refusal could have been failing open.

**Spec.** Codex's hooks are Claude-compatible, and Claude Code documents exit
2 as a blocking error whose stderr is fed back as the reason. Nothing in this
repository had observed Codex doing the same; `CodexAdapter.format_hook_output`
and `_fallback_profile` both said so in their docstrings.

**Fixture.** Three `codex exec` turns, one per variant, each in a fresh work
dir, each told to run exactly `touch marker.txt`. The probe hook is injected
with `-c hooks.PreToolUse=[...]` under `--dangerously-bypass-hook-trust`, so the
profile's own `hooks.json` and trust store are not edited; its deployed groups
still ran alongside and allow a `touch`. Every probe hook writes the payload it
received and its own exit code before answering.

* `control` — exits 0, nothing on stdout.
* `raw-exit2` — a bare script: reason on stderr, exit 2.
* `lh-refuse` — the installed `lh` 0.79.1 (which carries #460):
  `lh hook pre-tool-use-security --profile no-such-profile`, under an
  `LH_CONFIG_DIR` declaring one Claude Code profile and no Codex profile, so
  `_fallback_profile` refuses. Dry-run first with a hand-built Codex payload
  (`turn_id`, no `prompt_id`): exit 2, empty stdout, stderr `pre-tool-use-security:
  unknown profile 'no-such-profile'; declared: ['claude-probe']; no default
  profile to fall back to for a codex caller (0 declared codex profiles: [])`.

```bash
#!/usr/bin/env bash
# Probe: does Codex block a PreToolUse tool call when the hook exits 2 with an
# empty stdout (Claude Code's fail-closed channel)?
# Variants, one codex exec turn each, in a fresh WORK dir:
#   control   - hook exits 0, no stdout            -> marker must be created
#   raw-exit2 - hook exits 2, reason on stderr     -> ?
#   lh-refuse - real `lh hook pre-tool-use-security --profile no-such-profile`
#               under an LH_CONFIG_DIR that declares no codex profile, so
#               _fallback_profile refuses (exit 2)  -> ?
set -euo pipefail
OUT="${1:?out dir}"
mkdir -p "$OUT"
LHCFG="$OUT/lh-config"
mkdir -p "$LHCFG"
cat > "$LHCFG/config.toml" <<'TOML'
[harness]
version = "1"

[profiles]
default = "claude-probe"

[profiles.claude-probe]
identity = "probe"
config_dir = "~/.claude-probe-nonexistent"
TOML

mk_hook() {  # $1 label, $2 body
  local label="$1" dir="$OUT/$1"
  mkdir -p "$dir"
  cat > "$dir/hook.sh" <<EOF
#!/usr/bin/env bash
cat > "$dir/stdin.json"
$2
EOF
  chmod +x "$dir/hook.sh"
}
mk_hook control   'echo 0 > "'"$OUT"'/control/exit"; exit 0'
mk_hook raw-exit2 'echo "codex-exit2 probe: raw refusal via exit 2" >&2; echo 2 > "'"$OUT"'/raw-exit2/exit"; exit 2'
mk_hook lh-refuse 'set +e
LH_CONFIG_DIR="'"$LHCFG"'" lh hook pre-tool-use-security --profile no-such-profile < "'"$OUT"'/lh-refuse/stdin.json" > "'"$OUT"'/lh-refuse/stdout" 2> "'"$OUT"'/lh-refuse/stderr"
rc=$?
echo $rc > "'"$OUT"'/lh-refuse/exit"
cat "'"$OUT"'/lh-refuse/stdout"; cat "'"$OUT"'/lh-refuse/stderr" >&2
exit $rc'

for label in control raw-exit2 lh-refuse; do
  WORK="$OUT/$label/work"
  mkdir -p "$WORK"
  hook="$OUT/$label/hook.sh"
  set +e
  codex exec \
    --dangerously-bypass-hook-trust \
    --sandbox workspace-write \
    --skip-git-repo-check \
    -C "$WORK" \
    -c "hooks.PreToolUse=[{matcher=\"Bash|Read|Edit|Write|NotebookEdit\",hooks=[{type=\"command\",command=\"$hook\"}]}]" \
    --json \
    "Run exactly this one shell command and nothing else: touch marker.txt" \
    > "$OUT/$label/stream.jsonl" 2> "$OUT/$label/stream.stderr" < /dev/null
  echo "$?" > "$OUT/$label/codex-exit"
  set -e
  if [ -e "$WORK/marker.txt" ]; then m=present; else m=absent; fi
  echo "$label: codex-exit=$(cat "$OUT/$label/codex-exit") hook-exit=$(cat "$OUT/$label/exit" 2>/dev/null || echo never-ran) marker=$m"
done
```

Invoked as `CODEX_HOME=$HOME/.codex-lazy ./codex-exit2-probe.sh "$PWD/run1"`.

**Observed.**

| Variant | hook exit | hook stdout | `marker.txt` | `codex exec` exit | router line on stderr |
|---|---|---|---|---|---|
| `control` | 0 | empty | **created** | 0 | — (`command_execution` item, `exit_code: 0`) |
| `raw-exit2` | 2 | empty | **absent** | 0 | `ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: codex-exit2 probe: raw refusal via exit 2. Command: touch marker.txt` |
| `lh-refuse` | 2 | empty (0 bytes) | **absent** | 0 | `ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: pre-tool-use-security: unknown profile 'no-such-profile'; declared: ['claude-probe']; no default profile to fall back to for a codex caller (0 declared codex profiles: []). Command: touch marker.txt` |

Every captured payload was `hook_event_name: PreToolUse`, `tool_name: Bash`,
`tool_input.command: "touch marker.txt"`, a `turn_id`, `model: gpt-6-sol`,
`permission_mode: bypassPermissions`, and no `prompt_id` — the marker
`_caller_agent` reads still holds on 0.155.1. In both blocked turns the `--json`
stream carries no `command_execution` item, only the model's prose about the
block (`agent_message`), the same shape §6.4 recorded for an envelope deny. The
two `error` items every turn opens with are Codex's own warning about
`--dangerously-bypass-hook-trust`, not hook output.

**Reading.** Codex honours exit 2 as a refusal, and — like Claude Code — takes
the hook's stderr as the reason it reports. The fallback's refusal fails closed
under Codex. The spec and the observation agree; what changes is this
repository's own prose, which said the channel was unobserved and, in
`_fallback_profile`, that a cross-agent exit 2 made the hook fail open.

**Not measured.** Exit 2 *with* something on stdout (the runner never emits
that), exit codes other than 0 and 2, `apply_patch` rather than `Bash` (§3 shows
the envelope deny treating both paths alike, but this run did not repeat that
for exit 2), and events other than `PreToolUse`. The adapter keeps refusing with
the envelope on exit 0: it is the channel measured on both edit paths, and
nothing here is a reason to switch.

**Pinned by** `tests/unit/cli/test_hook_invoke.py::test_a_codex_caller_with_no_codex_profile_is_refused_on_exit_2`,
which drives the same `lh hook` invocation with the same payload shape and
asserts exit 2, empty stdout and the reason on stderr. Removing the final
`raise` in `_fallback_profile`, or turning the runner's blocking-failure exit 2
into 0, each makes it fail.

## Pendiente

Cerrado 2026-09-16 contra el binario real (`codex-cli 0.154.0`, modelo
`gpt-6-astra`, seis corridas desde Aqua en dos rondas): §1, §2, §3, y la tabla
de reconciliación F8 completa. El primer round (probes 1-4) dejó una lectura
equivocada en §2/§3 — un envelope de deny malformado hizo que Codex fallara
abierto, lo que se leyó como "el path nativo no está hookeado"; el segundo
round (probes 4b y 4c, envelope validado con `json.dumps`) la corrigió: el
deny funciona en los dos paths, y `apply_patch` SÍ dispara `PreToolUse` con
`tool_name: "apply_patch"`. Esa corrección se reflejó también en el design doc
padre (`specs/designs/2026-09-13-multi-agent-harness-design.md`, tabla de
claims y tabla de providers).

**§5 (Rollout format) se agregó después y también está cerrada** — medida el
2026-09-16 contra los mismos 15 rollouts de `codex-cli 0.154.0` (step 12, PR
#355), fuera del alcance de las seis corridas de arriba.

**Conclusión F8, cerrada:** mapear `apply_patch -> MODIFY_FILE` en
`_TOOL_OPERATIONS` es necesario pero no suficiente — hace falta además sumar
`"apply_patch"` a `INSPECTED_TOOLS` y, más importante, parsear el blob de patch
(`*** Update File: <path>`) en `FileEdit`s reales, porque `_parse_tool` nunca
lo hace hoy. El path `Bash` es estructuralmente no-gateable como edit,
independiente de cualquier mapeo: es un comando de shell arbitrario, sin campo
de path que extraer.

**No ejercitado por estas corridas:** §4 (state keying) — ninguno de los seis
probes tocó trust ni matchers, y queda con el alcance original documentado ahí.
`allow`/`ask` sobre un edit tampoco se corrió — de menor prioridad ahora que el
contrato de `deny` quedó confirmado en los dos paths, y sin usarse hoy en el
harness para Codex.

**§8 cerrada 2026-09-24** contra `codex-cli 0.155.1`: exit 2 con stderr bloquea
`PreToolUse` sobre `Bash` con stdout vacío. Sin medir: exit 2 sobre
`apply_patch`, exit 2 con stdout no vacío, exit codes distintos de 0/2, y
eventos distintos de `PreToolUse` (`specs/backlog.md` §Open Prioridad BAJA).

§4 cerró el 2026-09-17 con §4.1/§4.2 y sumó la medición cross-release de §4.3
el 2026-09-18.

**Cerrado además el 2026-09-16, probes 5-8 (`probe5-7.sh`, mismo binario,
modelo `gpt-5.6-sol`):** multi-file `apply_patch` (probe 5, dos secciones
`*** Update File:` en un solo blob), la grafía de delete (probe 6, `*** Delete
File: <path>` literal, sin diff body) y el dialecto de lectura (probe 7,
`list_mcp_resources` con `tool_input` vacío, sin reader nativo) — las tres
preguntas que quedaban abiertas en §2 arriba. `pre-tool-use-read-size` pasa de
"sin ejercitar" a límite estructural medido, en la misma clase que el path
`Bash`. Probe 8 midió además la forma de nivel superior de
`~/.codex/auth.json` (`auth_mode`, `OPENAI_API_KEY`, `tokens`,
`last_refresh`) — ver `specs/backlog.md` y ADR-045 para el uso de ese
hallazgo.

**Sigue sin correr:** la sub-forma de `tokens` dentro de `auth.json`, y la
probe 9 (keychain, ADR-045 A5) — no se corre desde un pane de agente.
