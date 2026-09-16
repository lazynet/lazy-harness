# Multi-agent harness: the blast radius outside the seam

**Status:** proposed (revision 4, 2026-09-13 — a third external review found ten defects, all confirmed against the code. Four were assertions drawn from a name or a docstring without exercising the path, and one of those inverted this document's central claim about how a downgrade fails)
**Date:** 2026-09-13
**Derives from:** [2026-09-13-multi-agent-harness-design.md](2026-09-13-multi-agent-harness-design.md) — every decision number cited as *parent decision N* refers to that document.
**Recorded as:** [ADR-041](../adrs/041-multi-agent-hook-contract.md), jointly with the parent — one decision, two documents. The items here that are deliberately *not* scheduled are in [`../backlog.md`](../backlog.md) under *Multi-agente — items declarados*, so an absent config entry reads as a decision rather than an oversight.
**Relates to:** [ADR-009](../adrs/009-profile-symlink-deploy.md) (profile symlink deploy), [ADR-012](../adrs/012-sqlite-monitoring.md) (SQLite monitoring), [ADR-032](../adrs/032-agent-adapter-completeness.md) (adapter completeness), [ADR-035](../adrs/035-capability-registry.md) (capability registry), [ADR-037](../adrs/037-metric-event-v2-host-and-workload.md) (metric event v2), [ADR-038](../adrs/038-exec-envelope-cost-provenance.md) (exec envelope cost provenance)

## Problem

The parent design bounds itself at the harness's own seam: the adapter Protocol,
the hook runner, the config artifacts, the system-document list. Everything
inside that boundary is accounted for.

Every one of those things has a consumer **outside** the boundary, and not one
of those consumers appears in the parent's twelve-step sequence. Four surfaces
were surveyed against the code rather than estimated: the metrics pipeline, the
system-document tree, the shell entry points, and the `lazy-ai-tools` monorepo.

The survey produced one result that changes the parent design's own success
criteria, one that changes a wire format, one that spans three repositories, and
one negative result worth as much as the others. They are reported in that
order.

## What the survey found

### 1. The kill criterion measures a number the pipeline cannot produce

The parent design's kill criteria read, before this document superseded them:

> **Adoption check:** total sessions on a non-Claude profile over the trailing
> four weeks, from the metrics store's `profile` label.
> **Kill threshold:** fewer than five such sessions in the last four weeks.

That number comes from `session_stats`, which is filled by exactly one path:

```python
# monitoring/ingest.py:121
projects_dir = profile.config_dir / "projects"
```

`"projects"` is a literal. Twelve call sites in `src/` ask the adapter where an
agent's sessions live — `cli/memory_cmd.py:241,269`, `cli/doctor_cmd.py:143,322`,
`cli/knowledge_cmd.py:224`, five hook builtins, `knowledge/compound_loop_worker.py:102`
and `hooks/builtins/pre_compact.py:161` — through
`agent.session_dirs()` (`agents/claude_code.py:143-144`). **The metrics ingest is
the only subsystem in the repo that does not.** Downstream of that literal,
`collector.iter_assistant_messages` parses Claude Code's `message.usage` shape,
and `TranscriptReader` for non-Claude agents is step **12** of the parent's
sequence — the last one.

So a Codex profile with two hundred sessions produces zero `session_stats` rows,
the adoption check at week eight reads zero, and the kill threshold fires. The
adapters are removed by an instrument that was never wired to them. This is not
a measurement that might be wrong; it is a measurement that is **structurally
incapable of being non-zero** for the entire horizon.

The parent's own gate names this class: *behavioural automation ships with kill
criteria … a measured baseline*. A baseline of zero read through an instrument
that can only report zero is not a baseline.

Three of those twelve call sites spell the lookup `agent.session_dirs().get("sessions") or "projects"`,
and a fourth `or "logs"`. For an adapter that declares no sessions directory the
fallback silently reinstates Claude Code's layout — the same fail-open, one level
down.

### 2. Cost is a per-token quantity, and two of the three agents are not billed that way

`DEFAULT_PRICING` (`monitoring/pricing.py`) holds twelve entries. Every key
starts with `claude-`. For anything else:

```python
# monitoring/pricing.py:179-180
rates = pricing.get(model)
if not rates:
    return 0.0
```

A model with no rate costs zero, and the row stores that zero. The only signal
that it was unpriced rather than free is `report.unknown_models`, which lives for
the duration of one ingest run and is never written to the row.

`is_pseudo_model` exists precisely because a genuine zero and a missing rate had
to be told apart for `<synthetic>`. The same distinction is now needed one level
up and for a different reason: Copilot CLI and Codex on a subscription are
**flat-rate**. The marginal cost of a session is genuinely zero and the total is
not attributable per session at all. That is a third state, and neither the
pricing table nor the stored row can express it.

The `lh exec` envelope has the same overload. `cost_source` takes
`"transcript"` (`cli/exec_cmd.py:148`), `"agent"` (`:453`), or `None` (`:68`).
`None` today means *we failed to price this*. ADR-038 exists because a null cost
on a run that was actually billed is an accounting hole. Adding a subscription
agent gives `None` a second meaning — *this is not priceable* — which is the
repo's own gate against one derived answer with two resolutions, in a field ADR-038
added to close exactly this.

### 3. `MetricEvent` has no `agent` dimension

```python
# plugins/contracts.py:16
METRIC_EVENT_SCHEMA_VERSION: int = 2
```

The v2 dimensions are `profile`, `session`, `model`, `project`, `date`, `host`,
`workload`. `aggregate.py:14` groups by the same set. Parent decision 7 makes a
profile an `(agent, identity)` pair, so `profile` *is* a faithful proxy — but
only by joining each row against `config.toml` **as it stood when the row was
written**. Config is mutable and rows are permanent: repoint
`[profiles.work].agent` and every historical row silently re-attributes.

ADR-037 is the precedent and the cost estimate: adding `host` and `workload`
meant a schema bump, coordination with every registered sink, and a
`from_dict` compatible with v1 payloads sitting in the outbox. The same applies
here, and `derive_event_id(profile, session, model)` (`event_id.py:14`) does not
need to change — profile still uniquely identifies the agent at write time.

### 4. The system-document tree is keyed by the Claude filename, across three repositories

`sync_agent_md.py` derives every path from the filename the adapter returns:

```python
stem = doc_name.removesuffix(".md")           # "CLAUDE"
common_path = profiles_dir / "_common" / f"{stem}.common.md"   # :62
head = entry / f"{stem}.head.md"                               # :71
tail = entry / f"{stem}.tail.md"                               # :72
```

Parent decision 6 replaces `system_doc_name() -> str` with
`system_docs() -> list[Path]`. Two consequences the parent notes for the deployer
but not for the generator:

- **There is no stem.** Copilot's user-level destinations are
  `copilot-instructions.md` and `instructions/**/*.instructions.md`. Neither
  yields a segment filename, and a list of two destinations yields two.
- **The segments are content, the destinations are targets, and today they share
  a name.** One rendered document must land at every path `system_docs()`
  returns. Keying the *source* segments by the *destination* filename forces a
  duplicate segment tree per agent for identical content — 193 of 199 lines
  identical, by the parent's own measurement.

The tree is not only in this repo. It is chezmoi source, deployed to
`~/.config/`, and symlinked into each profile dir per ADR-009:

```
dotfiles/dot_config/lazy-harness/profiles/_common/CLAUDE.common.md   (plain file)
dotfiles/dot_config/lazy-harness/profiles/{lazy,flex}/CLAUDE.head.md (plain file)
dotfiles/dot_config/lazy-harness/profiles/{lazy,flex}/CLAUDE.tail.md (plain file)
  → ~/.config/lazy-harness/profiles/…
  → ~/.claude-{lazy,flex}/CLAUDE.{md,head.md,tail.md}   (symlinks)
```

All eight sources are plain files, so a rename is a `chezmoi` source rename plus
a redeploy of the symlinks — no `.tmpl` / `modify_` / `symlink_` trap. That is the
cheap half. The expensive half is that renaming them breaks the hook that watches
them.

### 5. The sync hook is Claude-specific in three separate ways, and the user's own contract depends on it

```python
# hooks/builtins/post_tool_use_sync_claude.py
INSPECTED_TOOLS = frozenset({"Edit", "Write"})                       # :25
SEGMENT_FILES = {"CLAUDE.head.md", "CLAUDE.tail.md", "CLAUDE.common.md"}  # :27
DEFAULT_AGENT_TYPE = "claude-code"                                    # :29
```

Three of the parent's problems in twenty lines: Claude tool-name literals
(parent decision 9), a static list that should mirror what `system_docs()`
declares, and one of the nine hardcoded `get_agent("claude-code")` resolutions.
The module comment concedes the first two and defers them.

What makes this more than one more migration entry is that the hook's behaviour
is **documented in the deployed system document as a rule the user follows**:
editing `CLAUDE.common.md` in the chezmoi source rather than the destination is
called out as wrong precisely because it does not fire this hook. Rename the
segments per finding 4 and that rule silently stops holding, in a file whose
whole purpose is to be authoritative. The prose and the mechanism are already
coupled; the repo's gate requires they move together.

### 6. `lh run` is an argv passthrough, so `lcca` ships a Claude Code flag to whatever binary the profile resolves

```bash
# dotfiles/dot_config/zsh/20-aliases-common.zsh:59
alias lcca='lh run --allow-dangerously-skip-permissions'
```

The alias is the only Claude-named shell entry point in the dotfiles, and it is
**not** a Claude coupling: it goes through `lh run`, which resolves the profile,
the adapter and the binary through `agents/launch.py`. The name is Claude-shaped;
the mechanism is not.

The coupling is one line further in:

```python
# cli/run_cmd.py:85
exec_args = [argv0, *args]
```

Everything after `lh run` is forwarded verbatim. These are not one intent
under three spellings, and reading them as one is how a translation layer
silently widens a permission. Claude Code's own help distinguishes two flags:

```
--allow-dangerously-skip-permissions  Enable bypassing all permission checks
--dangerously-skip-permissions        Bypass all permission checks.
```

`lcca` uses the **first**: it makes bypass available, it does not turn it on.
The second turns it on. Codex's `--dangerously-bypass-approvals-and-sandbox`
turns it on *and* removes the sandbox — a third thing again. Copilot's
`--allow-all-tools` is a fourth point on the same axis.

On a Codex profile `lcca` fails at argv parse today, which is the *good*
outcome. The bad outcome is a mapping that treats all four as "the yolo flag"
and hands the user an activated bypass where they had only enabled one.

The parent design normalises the hook event, the tool arguments and the config
artifact. The command line is the fourth wire format between the harness and the
agent, and it is currently un-normalised by construction.

### 7. `.envrc` binds one env var per root, resolved from the global agent

```python
# cli/profile_cmd.py:32 — outside the loop that follows
adapter = get_agent(cfg.agent.type)
env_var = adapter.env_var()
for entry in cfg.profiles.items.values():
    for root in entry.roots:
        results.append(write_envrc(expand_path(root), env_var, config_dir))
```

Two defects the moment `agent` is per-profile. The adapter is resolved **once,
before the loop**, so every profile gets the default agent's env var. And
`_build_block` (`core/envrc.py:26-34`) emits a single `export` inside a single
marker-delimited block per root, so two profiles claiming the same root overwrite
each other's block — last write wins, silently.

Deployed today: `~/repos/lazy/.envrc:6` exports `CLAUDE_CONFIG_DIR=~/.claude-lazy`
and `~/repos/flex/.envrc:13` exports `CLAUDE_CONFIG_DIR=~/.claude-flex`. One
profile per root, one agent, no collision. Add a `lazy-codex` profile rooted at
`~/repos/lazy/` — the obvious first thing anyone does — and the collision is
immediate.

It is also the case that the *correct* end state is two exports in one block:
`CLAUDE_CONFIG_DIR` and `CODEX_HOME` in the same directory are not in conflict,
because each binary reads only its own. The block is not too small in principle;
it is built as if a root had one agent.

### 8. Negative result: `lazy-ai-tools` needs no changes

Surveyed the whole monorepo — `lazy-vault`, `lazy-tidy`, `lazy-cal`, four shared
packages, `tools/model-eval`, `skills/lazymind-projects`. Every model invocation
already routes through `lazy_shared_llm.headless.run()`, which spawns `lh exec`.
Nothing parses a transcript, reads `.claude/`, or implements the hook wire format.
The `[llm]` config declares capability tiers (fast / balanced / deep), not
provider names, and the harness maps tiers to providers.

What remains is nomenclature, not coupling: `ClaudeCallLog`
(`packages/lazy-vault/src/lazy_vault/execution_log.py:28-35`) and the
`StepLog.claude_calls` field (`:72`) keep their names for compatibility with 559
historical records, and several docstrings still say "processed with Claude Code"
about code that has not called Claude Code directly in months.

One genuine loose end: `tools/model-eval/run_spike.py:104` passes
`--model sonnet` to `lh run`. A tier name would survive a profile whose agent is
not Claude; a model name will not.

This is the result that justifies not widening the parent design. The reason
`lazy-ai-tools` is agent-agnostic is that `lh exec` was already the seam, which
is the strongest available evidence that the parent's abstraction is drawn in the
right place.

## Decisions

### 1. The adoption metric moves off the transcript pipeline

The kill criterion counts **launches**, not ingested sessions. `resolve_launch`
(`agents/launch.py`) appends one row before the agent binary is executed:

```sql
CREATE TABLE launches (
  ts      REAL NOT NULL,
  profile TEXT NOT NULL,
  agent   TEXT NOT NULL,
  host    TEXT NOT NULL DEFAULT '',
  entry   TEXT NOT NULL   -- 'run' | 'exec'
);
```

Append-only, no primary key: an event log, not state. It is agent-independent by
construction — recorded by the harness, needing nothing from `TranscriptReader`
and nothing from the agent's hook delivery.

**The row is written at the launch, not at the resolution.** `resolve_launch`
is the wrong place despite being where the profile and agent become known: both
callers invoke it *before* they honour `--dry-run` (`cli/run_cmd.py`, and
`cli/exec_cmd.py:217`), and `lh exec` also invokes it before rejecting an empty
prompt (`:221-227`). A counter there is incremented by rehearsals and by runs
that never happened, which for a five-event threshold is not a rounding error —
it is most of the signal.

So `resolve_launch` returns the plan and writes nothing; the write happens after
every validation and after the dry-run diversion, immediately before
`os.execvpe` (`cli/run_cmd.py:105` since the write landed above it) and
before the subprocess spawn in
`lh exec`. **The unit is a launch actually started**, not a launch attempted.
A failure to write must never block the launch.

**Shipped 2026-09-16.** The table is in `monitoring/db.py` under the same
`CREATE TABLE IF NOT EXISTS` pass as the other five, so every metrics DB on
disk gains it on the next open. `monitoring/launches.py:record_launch` is the
one write path both launchers call — fail-soft, one line to stderr, never
propagating — and it is called from `cli/run_cmd.py` immediately before
`os.execvpe` and from `cli/exec_cmd.py` after the empty-prompt refusal and
before the spawn, exactly as this decision requires. `resolve_launch` still
writes nothing. The read side is `MetricsDB.launch_counts` for the adoption
check's own grouping and `MetricsDB.launch_to_session_ratio` for the
calibration below. No CLI surfaces either yet; the horizon does not need one.

Rewritten criterion, replacing the parent's:

- **Baseline:** zero launches on any non-Claude profile.
- **Horizon:** eight weeks from the merge of the real `CodexAdapter` (parent step 9),
  not the throwaway from step 4.
- **Adoption check:** launches on a non-Claude profile over the trailing four weeks.
- **Kill threshold:** calibrated, not inherited — see the blind spot below.

**The unit is launches, and it is stated once.** The previous revision inherited
the parent's "sessions", which was measured one way and thresholded another —
the mistake the parent corrected in its own criteria, and this decision must not
reintroduce it one document later.

**Recorded blind spot.** `core/envrc.py:5` states the `.envrc` mechanism's
purpose as making the launcher unnecessary: *"any agent invocation inside the
root automatically picks up the right profile — no launcher needed"*. A session
started by typing `claude` or `codex` directly is invisible to this counter, and
that is not an edge case — it is the workflow the `.envrc` exists to enable.

So the counter **undercounts**, a threshold calibrated in sessions is stricter
in launches, and the failure direction is killing an adapter that was in use.
The mitigation is the repo's own rule — *a measured baseline, biased toward
false negatives*: before the horizon opens, measure the launch-to-session ratio
on the Claude profiles (`launches` rows against `session_stats` sessions over
the same window) and set the threshold from the observed ratio rather than from
the parent's five. If the ratio cannot be measured, the threshold is not set and
the horizon does not start.

Two alternatives were rejected, both because they reintroduce a dependency on
the agent:

- **A `SessionStart` hook row.** Counts real sessions and carries a genuine
  session id, but only on an agent that delivers the event — which is exactly
  what parent step 4 exists to verify, and `~/.copilot/hooks/` has never fired.
  Trading a transcript dependency for a hook dependency is the same
  structural-zero risk in a new place.
- **Reusing `session_attribution` with a null model.** Dead on the schema:
  `session TEXT PRIMARY KEY` (`monitoring/db.py:79-84`), written only by
  `lh exec` (`cli/exec_cmd.py:118`) because only `lh exec` pins a session id.
  The interactive path has none.

The alternative — pull `TranscriptReader` for Codex forward from step 12 to
before the clock starts — was rejected. The parent already gives the reason:
both non-Claude transcript formats are in migration, and a reader written today
is written against a version that will not ship. Blocking the kill criterion on
a reader that is deliberately last inverts the dependency.

**This decision survives the kill.** A launch counter is useful for Claude Code
alone.

### 2. `ingest` asks the adapter where sessions live, and the fallbacks are deleted

`ingest_profile` resolves its directory through `agent.session_dirs()` for the
profile's agent, like the other twelve call sites. The three
`or "projects"` fallbacks and the one `or "logs"` are removed: an adapter that
declares no sessions directory is skipped and named by `lh doctor`, which is the
parent's own degradation rule (*features degrade explicitly*), rather than
scanned as if it were Claude Code.

Ingest still cannot *parse* a non-Claude transcript — that is `TranscriptReader`,
and it stays at step 12. Decision 2 only ensures that when the reader lands,
ingest is already pointed at the right directory, and that until then a
non-Claude profile is reported as unreadable rather than reported as empty.

**The directories `session_dirs()` returns are measured, not assumed — including
one that does not exist.** Copilot 1.0.83 writes
`<copilot home>/session-state/<sessionId>/events.jsonl`, one JSON object per
line (`{"type":"session.start","data":{…},"id":…,"timestamp":…,"parentId":null}`),
95 such files present on this host, the newest self-identifying as
`copilotVersion: "1.0.83"` ([run], 2026-09-14). `history-session-state/`, the name this directory
has been referred to by elsewhere, **does not exist at that version** — verified
on disk 2026-09-14, and named here so it is not reintroduced. An entry pointing
at it would resolve to a missing path, which
`TranscriptHealth.NO_LOCATION` above does *not* cover, because the agent does
declare a location and the location is simply wrong. `session-store.db` sits
beside it and is not the transcript.

Codex 0.154.0 writes `<codex home>/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`
as the complete append-only log — 13 records for a one-turn session, including
`session_meta`, `response_item` and `token_usage_record` ([run]). The SQLite
stores **reference it rather than replace it**: `state_5.sqlite` holds index
rows whose `threads.rollout_path` points at that JSONL, and
`thread_history_1.sqlite` holds a projection of its items. So `session_dirs()`
for Codex names the rollout directory, and the parent's step-12 reader reads
JSONL for both non-Claude agents rather than one of each.

**What `lh doctor` reports is derived, not declared.** "Should this agent have a
reader?" has no configured answer and does not need one — the question that
matters is whether data is going unread:

```python
subdir = adapter.session_dirs().get("sessions") or ""
if not subdir:
    return TranscriptHealth.NO_LOCATION      # the agent declares none
sessions   = config_dir / subdir
has_data   = sessions.is_dir() and any(sessions.rglob("*.jsonl"))
has_reader = isinstance(adapter, TranscriptReader)
```

The absence of a location is handled **first**, and it has to be: `Path(x) / ""`
evaluates to `x` itself, so the obvious one-liner silently probes the whole
config directory and finds `settings.json` — every agent without a sessions
directory reported as degraded, on the strength of files that are not
transcripts. That is the same fallback-shaped fail-open this decision deletes
from `ingest`, and the previous revision reintroduced it two paragraphs after
deleting it. Matching session artifacts (`*.jsonl`) rather than any directory
entry is the second half of the same fix.

| Agent | Reader | Data | Reported |
|---|---|---|---|
| Claude Code | yes | yes | ok |
| Claude Code | no | yes | **degraded** — a real regression |
| Copilot | no | yes | **degraded** — accurate; `events.jsonl` exists and is unread |
| opencode | no | no | normal — it leaves no transcript to read |

`TranscriptReader` is a `runtime_checkable` Protocol in the parent design, so
`isinstance` is the whole test. Nothing is maintained by hand and the answer
tracks the code rather than a table someone has to remember.

Rejected: **a `transcript_reader` capability with a declared per-agent
expectation** in ADR-035's registry — a static list maintained beside the code,
which the repo's own gate says to derive from what it mirrors, and which would
require an adapter that *should* have a reader to declare its own defect. Also
rejected: **reporting the state with no verdict** — `lh doctor` exists to say
what is wrong, and a line that is never a problem is a line that stops being
read.

**This decision survives the kill.** It is a correctness fix and a hardcoded
literal removed.

### 3. Metric event v3: `agent`, and a billing model that admits flat rates

Three changes, one schema bump, in one ADR:

- `MetricEvent` gains `agent: str = ""`, appended with a default so v1/v2
  payloads still load through `from_dict` — the mechanism ADR-037 established.
  `aggregate.py` `DIMENSIONS` and `_STRING_DIMENSIONS` gain it. `derive_event_id`
  is unchanged.
- `cost_source` gains `"subscription"`. `None` returns to meaning exactly one
  thing: *we tried to price this and could not*.
- Pricing declares a **billing model** — `per_token` or `flat_rate` — resolved
  **per profile, from its execution context**, and persisted on every row
  alongside `cost_source`. A `flat_rate` row carries `cost = 0.0` with
  `cost_source = "subscription"` and does not fire `unknown_models`; a
  `per_token` row with no rate keeps firing it.

  Not per agent, which was the previous revision's answer and is wrong on this
  machine's own evidence: `~/.codex/auth.json` carries `auth_mode`,
  `OPENAI_API_KEY` **and** `tokens` at once. The same agent bills by
  subscription under a ChatGPT sign-in, per token under an API key, and nothing
  at all under `--oss` against a local model — the mode the parent's step 4 gate
  uses. Stamping `flat_rate` on "codex" would report an API-key profile's real
  spend as zero, which is the failure this decision exists to prevent, relocated
  one level up.

  It is persisted rather than recomputed because the auth mode is mutable and
  the row is permanent — the same argument that puts `agent` on the event.

**Rendering, which is where the distinction is either kept or thrown away.** A
`flat_rate` profile keeps its sessions row and its tokens row — the usage is
real. Its cost renders as `—`, never `$0.00`. And it is excluded from the `all:`
rollup, which is relabelled *priced only*:

```
Sessions  lazy:  12 today · 88 month
          beta:   3 today · 14 month
          all:   15 today · 102 month

Tokens    lazy:  4.2M in · 310K out · $48.10 (sep)
          beta:  1.1M in ·  90K out · —      (sep)
          all:   5.3M in · 400K out · $48.10 (sep, priced only)
```

This follows the precedent already documented in the same file
(`monitoring/views/overview.py:89-94`): the cache line is kept off the tokens
row on purpose, because two numbers that do not belong in one aggregate are not
put in one aggregate. A flat-rate zero summed into a per-token total is that
same conflation. In JSON the cost is `null` alongside `cost_source`, so a
machine consumer distinguishes the cases without parsing the render.

Rejected: **excluding flat-rate profiles from the cost views entirely** — it
hides real usage, which is the opposite error to `$0.00` and no smaller. And
**amortising the subscription fee across the month's sessions** — it is the only
option that permits a marginal-cost comparison across agents, but the number is
fabricated, it mutates retroactively as sessions land, and it requires the fee
to be declared in config where the harness cannot verify it.

The alternative — omit `agent` and join against config — is rejected above:
config is mutable and rows are permanent.

**This decision dies with the kill**, except `cost_source = "subscription"`,
which is cheap enough to leave in place.

### 4. Segments are named by role, not by destination filename

The segment tree loses its stem:

```
_common/common.md              shared rules
_common/<agent>.md             agent-specific segment   (new)
<profile>/head.md              identity
<profile>/tail.md              per-profile context
```

`render_agent_md` composes `head + common + agent + tail` and the deployer writes
the identical rendered bytes to **every** path `system_docs()` returns. The
agent-specific lines the parent counted — `TaskCreate`/`TodoWrite`, subagent
model routing, `/rewind` / `/compact` / `/clear` — move into
`_common/claude-code.md`. An agent with no segment renders without one; that is
the common case, not an error.

**The agent segment is shared across profiles, not per profile**, and that is a
measurement rather than a preference. In the deployed tree every one of those
agent-specific lines is already in `_common/CLAUDE.common.md`; `lazy/CLAUDE.head.md`
(4 lines), `lazy/CLAUDE.tail.md` (40), `flex/CLAUDE.head.md` (5) and
`flex/CLAUDE.tail.md` (35) contain none. The content is identity-independent in
practice today, so `<profile>/<agent>.md` would take something that lives in one
file and split it into one copy per profile — a duplication introduced to serve
no observed need.

A per-profile override (`<profile>/<agent>.md`, appended after the shared one)
is additive to this layout and costs nothing to add later. It is deferred until
a second profile actually needs to say something different about the same agent.
One agent and zero divergent profiles is not a pattern.

This is the parent's second axis, implemented so that it costs one file per
agent rather than a duplicated tree per destination filename.

Migration is a chezmoi source rename of eight plain files, `chezmoi apply`, and
`lh deploy` to relink. The generated-header text
(`GENERATED_HEADER_TMPL`, `sync_agent_md.py:27-30`) names the segment files and
the command, so it is regenerated by the same change — it is written into every
deployed document and is the most-read line in the tree.

### 5. The sync hook derives its triggers, and is renamed

`SEGMENT_FILES` is computed from the segment roles in decision 4 rather than
listed, with a test asserting it against the directory glob — the repo's gate on
static lists that mirror a directory. `INSPECTED_TOOLS` becomes an `Operation`
set (`MODIFY_FILE`) per parent decision 9. `DEFAULT_AGENT_TYPE` is deleted with
the other eight.

`post_tool_use_sync_claude` → `post_tool_use_sync_system_doc`, and
`lh profile sync-claude-md` → `lh profile sync-system-doc`, the old name kept as
an alias. **The paragraph in the deployed system document that documents this
hook's trigger is updated in the same commit as the rename.** The prose names the
mechanism; the gate requires both halves move together, and this is the one place
in the blast radius where the reader of the prose is a person who will act on it.

### 6. Permission-bypass is a declared intent, not a forwarded flag

The axis has three positions, not one, and the adapter declares each
separately:

```python
class Bypass(StrEnum):
    ENABLE   = "enable"    # make bypass available; do not turn it on
    ACTIVATE = "activate"  # turn it on
    NO_SANDBOX = "no_sandbox"  # also remove the sandbox, where one exists

def bypass_argv(self, level: Bypass) -> list[str] | None:
    """Flags for this level, or None if this agent has no such level."""
```

`lh run --bypass=enable|activate|no-sandbox` expands one of them. **`lcca`
becomes `lh run --bypass=enable`**, which is what
`--allow-dangerously-skip-permissions` means today — the migration preserves the
alias's semantics exactly, and that is the point. A single `--yolo` was the
previous revision's proposal and it is withdrawn: it collapses three positions
into one, and the direction it collapses them in is *more* permissive.

An adapter returning `None` for a level makes that level an error naming the
agent, rather than a flag forwarded to a parser that may or may not reject it.
An agent with no sandbox has no `NO_SANDBOX`; that is a reported state, not a
silent alias for `ACTIVATE`.

Every other argument stays a passthrough. This is deliberately one axis, not a
general argv translation layer: it is the only forwarded flag whose
misinterpretation is a safety property rather than a usability one, and a
general translator would be the "unified model that lies in every direction" the
parent rejected for permissions.

Rejected: leaving `lcca` as-is and documenting that it is Claude-only. The alias
is the single most-used entry point into the harness, and "this alias is unsafe
on some profiles" is a footnote no one reads at the moment it matters.

### 7. `.envrc` blocks carry one export per agent claiming the root

`deploy_envrc_for_all_profiles` resolves the adapter **inside** the profile loop
via `agent_for_profile(cfg, name)` (parent decision 7). `write_envrc` accumulates
one `export <env_var>="<config_dir>"` per distinct agent among the profiles
claiming that root, in one managed block.

Two profiles with the **same** agent claiming the same root remains an error —
it is genuinely ambiguous, direnv cannot express it, and it is reported by
`lh doctor` rather than resolved by last-write-wins.

**The exports are only half the problem.** `.envrc` tells each binary which
config dir to read; it does not tell `lh run` which binary to start.
`resolve_profile_with_source` picks the longest matching root with
`len(root_str) > best_len` (`core/profiles.py:101`) — strictly greater, so two
profiles sharing a root resolve to whichever appears **first** in
`cfg.profiles.items`, which is TOML document order. The agent you launch would
depend on the order of your config file, silently.

The tie is therefore not broken, it is refused: with two profiles claiming a
root, `lh run` without `--profile` exits with an error naming both, unless the
root declares a default. That declaration is the new field:

```toml
[profiles.lazy]
roots = ["~/repos/lazy"]
root_default = true      # this profile answers a bare `lh run` in a shared root
```

Exactly one profile per root may set it; two is the same error, reported by
`lh doctor` before it is ever hit. Refusing beats guessing here because the
guess is invisible in the output — `lh run` announces the profile only when it
differs from the default (`cli/run_cmd.py:96-99`).

**This decision survives the kill** as far as the loop fix; the multi-export
block only matters with a second agent.

### 8. `lazy-ai-tools` is out of scope, and the nomenclature debt is recorded unpaid

No change. `ClaudeCallLog`, `StepLog.claude_calls` and the stale docstrings are
renamed only if something else already touches those files — renaming 559
historical records to fix a name is exactly the refactor-outside-the-task this
repo forbids.

The one substantive item, `run_spike.py:104` passing `--model sonnet`, becomes a
tier. It is a one-line change in a spike tool and does not need this design.

## What does not change

Stated explicitly, because a blast-radius document that lists only impacts
overstates the blast radius.

| Surface | Status |
|---|---|
| `lazy-ai-tools` (9 packages) | agent-agnostic already; routes through `lh exec` |
| MCP server declarations | already in `config.toml`; parent design confirms portable |
| Skills, slash commands | placement only |
| `.envrc` as a mechanism | correct; the generator that writes it is not |
| `lcca` as an entry point | goes through `lh run`; only the flag it forwards is wrong |
| `derive_event_id` | profile still identifies the agent at write time |
| Engram / QMD / Graphify | no code in `lazy-ai-tools` references them; out of scope here |

## Consequences

**Positive**

- The parent design's kill criteria become measurable. Today they are not, and
  that defect would have surfaced at week eight as a false negative, after the
  work was done.
- The metrics pipeline stops being the one subsystem that ignores
  `session_dirs()`; four fail-open fallbacks go with it.
- A zero in the cost column becomes readable: free, unpriced, or not priced
  per token.
- The system-document tree stops multiplying by destination filename. One
  rendered document, N destinations, one segment per (profile, agent).
- The single riskiest forwarded flag stops being forwarded blind.
- A twelve-step migration across several sessions becomes reversible at each
  step, and the beta surface is bounded by a profile rather than by a machine.

**Negative**

- A metric event schema bump, with the sink coordination ADR-037 documents.
- Renaming eight chezmoi-managed segment files touches three repositories and the
  deployed profile symlinks in one change, and the hook that watches them must
  land in the same release or the sync silently stops firing.
- Decision 4 changes a file layout that a human edits by hand, and the muscle
  memory is `CLAUDE.head.md`.
- `--bypass=<level>` is a new user-facing flag on the most-used command, and
  `lcca` changes shape even though its meaning is deliberately preserved.
- Decision 11 acquires two prerequisites that did not exist when it was written
  — a profile-scoped `lh deploy` and a second installable entry point — and the
  second is still undecided.
- The rollback log gains a manifest format, and `apply_rollback_log` gains a
  branch, so two restore contracts coexist.
- `lh deploy` gains a snapshot on every run, which is a write it did not make
  before, and a rollback log that can itself go stale.
- `harness_binary` is a config key whose only consumer is a beta workflow. It is
  the config-promise-with-no-implementation shape the parent design rejects
  twice, and it is justified here only because the alternative — a path in
  `hook_command` — breaks chezmoi convergence. If the beta profile is not used
  within one release cycle, the key comes out.

## Sequence

Mapped onto the parent's numbered steps rather than numbered independently.

| Parent step | Derived work | Must land by |
|---|---|---|
| **0** (fix `_is_harness_owned`) | decision 9 — the version marker | **with step 0**; without it every later round trip accumulates stale entries |
| 1 (contracts, runner takes `--profile`) | decision 11 — `harness_binary` per profile | with the runner, or it costs a second pass over `hook_command` |
| 3 (config deploy slice) | decision 11's prerequisite — `lh deploy --profile <name>` scoping all four deploy steps | **before any beta claim**; the engine is already being rewritten there |
| 2 (runner, 3 builtins) | decision 5 — the sync hook is not one of the three, but its `DEFAULT_AGENT_TYPE` is one of the nine | with the nine |
| 3 (config deploy slice) | decision 7 (loop fix only) | before step 4 |
| 3 (config deploy slice) | decision 10 — `--snapshot` / `--rollback` | before the first deploy that changes an artifact's shape |
| **4** (contract gate) | decision 2 — otherwise the gate cannot show a Codex session as *unreadable* rather than *absent* | **before the gate** |
| 6 (per-profile agent) | decision 7 (multi-export block) | with `agent_for_profile` |
| 8 (`system_docs()`) | decisions 4 and 5 (rename + prose) | same release |
| **9** (real `CodexAdapter`) | decision 1 — the horizon clock starts here | **before the clock**, and the threshold is calibrated before it opens |
| 9 | decision 6 — `--bypass` levels; the first profile where a forwarded flag can be wrong | with the adapter |
| 10 (`lh doctor` per profile) | decision 2's derived transcript health | with the rest of the per-profile doctor work |
| any | decision 3 | before the first non-Claude cost is reported |
| — | decision 8 | not scheduled |

Decisions 1, 2, 6 and the loop half of 7 are correctness work for Claude Code
alone and survive if the kill criteria fire. Decisions 3 and 4 do not.

## Staging and rollback

The parent design is twelve steps across several sessions, and step 4 is a gate
that can fail. Neither document says how a half-migrated machine gets back to a
working one. This section is the mechanism, and it is scoped to what the survey
found is actually at risk rather than to rollback in general.

### The binary half is already solved

`lh` is installed through `uv tool install` pinned to a git tag:

```toml
# ~/.local/share/uv/tools/lazy-harness/uv-receipt.toml
requirements = [{ name = "lazy-harness", git = "https://github.com/lazynet/lazy-harness?rev=v0.59.0" }]
```

Reverting the binary is one command against a different tag. Nothing in this
section is about that.

### The deployed state is not versioned with the binary

`lh deploy` writes artifacts — `settings.json` hook entries, profile symlinks,
`.envrc` blocks, MCP config — and none of them records which version wrote them.
Reverting the binary under artifacts a newer one wrote is undefined behaviour
today. Measured, per surface:

| Surface | On downgrade | Severity |
|---|---|---|
| `settings.json` hook entries | Parent decision 1 changes the command from `lh hook <name>` to `lh hook <name> --profile <p>`. Click rejects the unknown option *before* the callback, so `hook_invoke`'s `try/except` is never reached: measured, `lh hook context-inject --zzz` exits **2** with a usage message on stderr. On `PreToolUse` exit 2 means **deny**, so every tool call is refused with Click's usage text | **Loud and total** — a work stoppage, not a hole |
| Segment filenames (decision 4) | The old `sync_agent_md` looks for `CLAUDE.head.md`, finds `head.md`, and `sync_profiles` becomes a no-op. The deployed document stays at its last generated content — stale but valid | Silent |
| `session_stats` (decision 3) | Safe. `db.py` migrations are idempotent `ALTER TABLE … ADD COLUMN … DEFAULT`, and the read path selects by explicit column name (`db.py:417`), so an extra `agent` column is invisible to the old reader. `MetricEvent.from_dict` has no caller in `src/` | None |
| Remote sink | Already holds v3 payloads. This is the remote's forward-compatibility problem, not a local downgrade | None locally |
| `config.toml` | Plain dataclasses over `tomllib`; unknown keys are ignored, so `[profiles.<name>].agent` falls back to the global `agent.type` | Tolerable |

**The previous revision had this row exactly backwards**, and the correction is
worth keeping rather than quietly fixing. It claimed the old binary would reject
the flag inside `hook_invoke`, hit the broad `except`, and exit 0 — a blocking
hook failing *open*. Running it settles it: Click raises `UsageError` during
parameter parsing, before the command callback is entered, and exits 2. The
`try/except` at `cli/hooks_cmd.py:87-108` sits inside the callback and never
sees it.

So the failure is **fail-closed and loud**: on `PreToolUse`, exit 2 is Claude
Code's block verdict, and the refusal reason shown is a Click usage string. The
machine does not quietly lose its safety net; it stops working, visibly, on the
first tool call.

That is a better failure than the one this document claimed, and it changes what
the mitigation is for. The risk is no longer a silent security regression — it
is that the reason on screen is a usage error that names an option, and nothing
tells the user their artifacts are newer than their binary. Decision 9 survives,
with diagnosability rather than safety as its justification.

The error class is worth naming, because it is the same one the parent's second
review found: a behavioural conclusion drawn from reading code rather than
running it. Four of this revision's ten corrections are that class.

### The defect at parent step 0 is what makes a round trip accumulate garbage

`_is_harness_owned` (`deploy/engine.py:86`) matches on the substring
`lazy_harness/hooks/builtins/`, while `hook_command` (`:33`) generates
`lh hook <name>`. It never matches. Today that is masked: the merge's *second*
guard skips an existing entry whose command is in this run's generated set
(`:149`), and the two strings are identical, so no duplicate appears.

It stops being masked the moment the command format changes — which is exactly
what parent decision 1 does. Deploy the new format and the old entry is
preserved beside the new one, because guard 1 is broken and guard 2 no longer
matches. Roll the binary back, deploy again, and the *new*-format entry is
preserved beside the restored old one. **Every change of direction leaves one
more stale entry, and each one runs the hook again.**

This is why parent step 0 is step 0. It is also why rollback cannot be built on
top of the merge as it stands.

### Decision 9: a deployed artifact declares the version that wrote it

Every managed block and generated file carries the writing version —
`lh_version` in the `settings.json` managed section, in the `.envrc` block
notice, and in `GENERATED_HEADER_TMPL`. On startup, any command that reads a
managed artifact compares it against `lazy_harness.__version__` and reports a
newer artifact through `lh doctor`.

Reporting, not refusing. A hard refusal turns a stale artifact into an
unusable machine, and the failure this closes is silence, not the mismatch
itself. The one exception is a **blocking** hook: the runner (parent decision 1)
refuses to run against an artifact written by a newer version and exits 2 with
the reason, because for a blocking hook the safe default is to block. That
inversion is the repo's own rule for blocking hooks, applied to a new input.

This is the cheapest of the three, and it converts the one genuinely confusing
row above — a Click usage error offered as the reason a tool call was denied —
into a sentence that names the actual cause.

### Decision 10: `lh deploy --snapshot` and `lh deploy --rollback`

Modelled on `lh migrate`, which already has every piece: a timestamped backup
directory under `~/.config/lazy-harness/backups/<ts>/`, a plan built before
anything is written, a **rollback log** replayed by `apply_rollback_log`, and a
`record_dry_run` / `check_dry_run_gate` pair that requires a dry run within the
hour before a real one. `lh deploy` has none of it, and the asymmetry between
the two commands is the defect — a migration is reversible and a deploy, which
runs far more often, is not.

`lh deploy` takes a snapshot before writing and appends a rollback log.
`lh deploy --rollback` replays the latest, exactly as `lh migrate --rollback`
does. The plan-then-execute split already exists in `deploy/engine.py`; what is
missing is that the plan is not persisted.

**The rollback log needs a new contract before it can be reused.**
`apply_rollback_log` restores a file by basename — `src = backup_dir / Path(payload["path"]).name`
(`migrate/rollback.py`) — which was sufficient for a migration touching one of
each file and is not sufficient here: `~/.claude-lazy/settings.json` and
`~/.claude-flex/settings.json` are two different files with one basename, and
the second restore would overwrite the first profile's artifact with the
second's.

A second defect in the same function is closer to silent: `restore_symlink`
acts only `if not link.exists()`, so it recreates a *deleted* symlink and never
repoints an existing one. Every profile artifact under ADR-009 is an existing
symlink, so a rollback of a relink would report success and change nothing.

So the snapshot writes a **manifest**, not a directory of loose files: one entry
per artifact carrying its absolute destination, its kind (file, symlink,
managed-block-in-a-foreign-file), the symlink target where that applies, and a
content path inside the snapshot that is unique per destination rather than per
basename. `apply_rollback_log` gains a manifest branch; the migration branch
stays as it is, because rewriting it would change a path that works for a
command nobody is changing.

**Unconditionally, on every deploy, pruned to the last ten by count.** The
managed artifacts measure ~135 KB in total on this machine — `settings.json`
14.9 KB and 15.4 KB across the two profiles, `.claude.json` 104 KB, `.envrc`
244 bytes — so ten snapshots cost ~1.35 MB against the 8.2 MB metrics DB this
decision already declines to copy. Triggering on a version change, or on a plan
that differs from disk, are both optimisations of an operation that is already
cheap, and each adds a condition that can be wrong in the direction of *no
snapshot when one was needed*. A plan-diff trigger is also not free: it needs a
persisted, comparable plan, and `deploy/engine.py` has neither.

**The two backup namespaces must not share a parent.** `_latest_backup_dir`
(`cli/migrate_cmd.py:29-34`) returns the newest directory under
`~/.config/lazy-harness/backups/`, whatever wrote it. Writing deploy snapshots
beside migration backups makes `lh migrate --rollback` replay a deploy's
rollback log, and makes a deploy prune delete a migration backup. They split
into `backups/migrate/<ts>/` and `backups/deploy/<ts>/`, and `_latest_backup_dir`
takes the namespace as an argument — one function, two callers, no shared
newest-wins directory. Existing top-level timestamped directories are migration
backups and are read from the old location for as long as they exist.

Deliberately **not** included: snapshotting the metrics DB. It is 8.2 MB, its
migrations are additive and idempotent, and the survey found no downgrade break
in it. Backing it up on every deploy would be the expensive half of a rollback
that protects nothing.

### Decision 11: the beta unit is a profile, not an installation

A profile already carries its own `config_dir`, its own deployed artifacts, its
own symlinks, and — after parent decision 7 — its own agent. It is the natural
blast-radius boundary.

**It is not yet a deployable one, and the previous revision asserted otherwise.**
`lh deploy` (`cli/deploy_cmd.py:39`) takes no options, and `_run_deploy` calls
`deploy_profiles`, `deploy_hooks` and `deploy_mcp_servers`, each of which walks
every profile in the config. There is no way today to deploy one profile and
leave the others untouched, so "deploy the beta profile" is not a thing the
harness can do. `lh deploy --profile <name>`, scoping all four steps, is a
prerequisite of this decision rather than a convenience alongside it — and it
belongs with step 3's vertical slice, where the engine is already being
rewritten.

A `beta` profile is deployed from the branch build; `lazy` and `flex` stay on
the released tag. Rollback for the beta is deleting the profile, which touches
nothing the daily profiles read. The parent's own gate — *deploying a hook is
binary-first, never from a worktree* — is satisfied, because the beta profile
still points at an installed binary, just a different one.

That last part is the constraint that makes this real work rather than a
convention: `hook_command` writes a bare `lh` with no path, deliberately, so
that a chezmoi-managed `settings.json` converges across machines. A beta profile
needs its hooks to reach a *different* binary than the daily profiles do, and no
current mechanism can express that.

The resolution is not to put a path back in the command. It is that the runner
introduced by parent decision 1 already takes `--profile`, and a profile can
declare which installed binary serves it:

```toml
[profiles.beta]
config_dir = "~/.agent-beta"
agent = "claude-code"
harness_binary = "lh-beta"     # resolved from PATH, like `lh`
```

`hook_command` becomes
`f"{binary_for_profile(cfg, p)} hook {hook.name} --profile {p}"` — the
`--profile` is parent decision 1's and is not optional; the previous revision's
example dropped it —
still a bare name resolved by `execvp`, still machine-independent, still
convergent under chezmoi. **The beta capability falls out of parent decision 1
rather than being added on top of it**, which is the whole reason it is
affordable.

**How `lh-beta` gets installed is also unsettled, and the previous revision's
answer does not work.** `[project.scripts]` declares exactly one entry point,
`lh = "lazy_harness.cli.main:cli"`, so no invocation of `uv tool install`
produces a binary called `lh-beta`: `--with-executables-from` selects which
package's existing entry points to install, it does not rename them, and two
`uv tool install` runs of the same package name replace each other rather than
coexisting.

Two workable shapes, neither free:

- **A second entry point.** `pyproject.toml` declares `lh-beta` alongside `lh`,
  both pointing at the same `cli`. Every install then carries both names, which
  is a public surface added for a private workflow — but it is three lines and
  `uv tool install --from git+…@<branch>` then genuinely produces it.
- **A separate tool name.** Publish the branch under a distinct project name so
  `uv tool` treats it as a different tool. Cleaner isolation, and it means a
  branch build cannot be installed without editing `pyproject.toml` on that
  branch — which is arguably the right amount of friction for a beta.

The second is preferable and neither is decided here. What matters for the
sequence is that **decision 11 is blocked on both prerequisites**, and claiming
the beta profile as an isolation guarantee before they exist would be the
config-promise-with-no-implementation shape this document criticises twice.

### Why not a release-please prerelease channel

`.github/release-please-config.json` declares no prerelease type, and adding one
means a release branch, prerelease tags, and a second changelog stream —
permanent process for a temporary need. Installing from a branch rev is the same
`uv tool install` already in the receipt, produces no artifacts to clean up, and
reverts by pointing at the tag again.

If a second person ever installs this framework, the prerelease channel becomes
worth its cost. Today it is not.

### What this section does not cover

Chezmoi. The segment rename in decision 4 is a `chezmoi` source rename, and
chezmoi's own history is the rollback for it. Rebuilding that inside `lh` would
be a second home for a mechanism that already exists — with the caveat that
`chezmoi apply` and `lh deploy --rollback` are two operations and nothing
sequences them. Reverting a segment rename means both, in that order.

## Verification gates

- **The adoption metric is verified by producing a non-zero reading before the
  horizon starts.** Launch one session on a throwaway non-Claude profile and
  query the counter. A kill criterion whose instrument has never returned a
  non-zero value has not been tested — it has been declared.
- **The `session_dirs()` fix is verified from a profile whose adapter returns a
  directory that is not `projects`.** A fake adapter returning `"sessions"`, with
  ingest asserted to walk it and to skip — not scan — an adapter returning `""`.
- **The v3 schema is verified through a full round trip on a v1 and a v2 payload
  taken from the outbox**, not a constructed one, and the remote sink is queried
  after ingest to confirm `agent` arrived. ADR-037's own gate.
- **A `flat_rate` agent's zero is distinguished from a `per_token` agent's zero
  in a query, not in a comment.** One row of each, one `lh status` invocation,
  the two rendered differently.
- **The segment rename is verified by reading the deployed symlink target**, not
  by a successful `chezmoi apply`: `cat ~/.claude-lazy/CLAUDE.md` after the
  rename, and again after editing a segment, to confirm the hook still fires
  under its new trigger set. Exit codes are not proof of effect.
- **The prose half of decision 5 is grepped in both directions.** Every filename
  the deployed system document names must exist in the segment tree, and every
  segment role must be named there.
- **`bypass_argv` is tested with an adapter returning `None` for a level**, and
  the error asserted to name both the agent and the level. A duck-typed
  capability is tested with the capability absent.
- **The `.envrc` block is verified by `direnv export` in a root claimed by two
  profiles with different agents**, asserting both variables present — not by
  reading the generated file.
- **The derived transcript-health verdict is verified against all four rows of
  its own table**, each with a fake adapter — including the two that must *not*
  report degraded. A check that returns the same verdict for every input covers
  nothing.
- **The version marker is verified by a real round trip, not a mismatch
  fixture.** Deploy at version N, deploy at N+1 with a changed command format,
  deploy at N again, and assert `settings.json` holds exactly one entry per hook
  at each point. This is the test parent step 0 is missing, extended to the
  direction that actually happens during a staged migration.
- **The blocking-hook refusal is exercised with the marker newer than the
  binary**, asserting exit 2 and the reason on stderr — the inverted gate: for a
  blocking hook, exit 0 is the failure.
- **`lh deploy --rollback` is verified by diffing the artifacts, not by its exit
  code.** Snapshot, deploy a change, roll back, and assert every managed file is
  byte-identical to the snapshot. A tool's exit code is not proof of its effect.
- **The beta profile is verified by observing a hook fire from the beta binary
  while a daily profile's hook fires from the released one**, in the same
  session on the same machine. Two binaries is the claim; one `lh doctor` per
  profile is not evidence for it. `lh deploy --profile beta` is asserted to
  leave every other profile's artifacts byte-identical — the isolation claim,
  tested as an isolation claim.
- **Each `Bypass` level is verified against the agent's own help output**, not
  against the adapter's table: assert the flag `bypass_argv` returns is a flag
  the installed binary documents, and that `ENABLE` and `ACTIVATE` map to
  different strings wherever both exist. The defect this replaces was two flags
  read as one intent, and only the binary can refute that.
- **The launch counter is asserted to stay at zero across a `--dry-run` and an
  empty-prompt rejection**, on both `lh run` and `lh exec`. A counter tested
  only on the happy path cannot show that it counts the wrong things.
- **The billing model is exercised with one agent under two auth modes**, the
  same adapter resolving `per_token` for one profile and `flat_rate` for
  another in a single run — the case a per-agent table cannot represent.
- **The rollback manifest is verified with two profiles whose artifacts share a
  basename**, and with an existing symlink that must be repointed rather than
  created. Both are the cases the current `apply_rollback_log` gets wrong.

## Open questions

1. **What is the calibrated kill threshold?** Decision 1 fixes the instrument
   and the unit; the number depends on a launch-to-session ratio nobody has
   measured. It is a measurement with a defined method, not a judgement, and it
   gates the *start of the horizon*, not the start of the work.

   **Attempted 2026-09-13; the ratio cannot be computed, which confirms decision
   1 rather than answering it.** There is no numerator. `git log -S "CREATE
   TABLE launches" --all` returns exactly one commit — `202d1d2 docs(design)`,
   the commit that added *this document's own SQL block*. The string has never
   existed in code, only in prose here.

   Two candidate proxies were checked and both rejected:

   - `session_stats` cannot stand in for either half. It holds **more** distinct
     sessions than there are transcripts on disk (lazy: 3619 rows against 2413
     `.jsonl` files; flex: 3532 against 1295), because rows survive the
     transcripts they describe. Even as a denominator it needs a stated window
     — filtering on the session `date` column rather than file presence, e.g.
     `date >= date('now','-28 days')`, sidesteps the accumulation.
   - `loop_events.kind = 'session_closed'` is written by the compound-loop hook,
     not by a launcher, so it counts the wrong event to begin with. It also
     starts only at 2026-08-16, a fraction of `session_stats`' range, and 174 of
     its rows carry an empty `profile` label — unattributable to either profile.

   The instrument in decision 1 has to be built and given a real baseline window
   **before** the horizon clock can start, which is what that decision already
   says. What this measurement adds is that there is no interim proxy to start
   the clock against in the meantime, so the parent's step 9 must not be treated
   as the clock's start until the table exists and has accumulated a window.

   **Still open 2026-09-16; the instrument exists now, the number does not.**
   `MetricsDB.launch_to_session_ratio(days=...)` implements exactly the
   measurement described above: launches against `COUNT(DISTINCT session)` from
   `session_stats`, both halves cut at one instant floored to the same local
   midnight, because `launches.ts` is an epoch and `session_stats.date` a local
   day and a window bounding only the numerator would divide a month of
   launches by every session ever ingested. The helper returns `ratio: None`
   for a profile whose window holds no sessions — uncalibrated, not infinite.
   What is still missing is elapsed time: the table starts empty on every
   machine, so the first honest reading is one accumulated window after this
   ships. The rule in decision 1 is unchanged — no ratio, no threshold, no
   horizon.
2. **Copilot's real `preToolUse` payload, and whether it honours `deny`.**
   **Closed 2026-09-13 by measurement against copilot 1.0.83** — the payload is
   the camelCase shape with `toolArgs` as a nested object, `deny` is honoured, a
   nonzero exit fails closed, and a timeout fails **open**. Evidence and the
   literal payload are in the parent design's *Closed by measurement* section.

   The consequence lands on decision 6: a `--bypass` level that reasons about
   what a hook will refuse is reasoning about a hook that stops refusing
   anything the moment it runs slow. On Copilot, a deny-carrying hook's timeout
   is part of its security contract and belongs in what `lh doctor` reports.
