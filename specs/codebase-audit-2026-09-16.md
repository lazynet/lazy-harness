# Codebase Architecture & Quality Audit

Audit date: 2026-09-16. Source references reflect the code inspected on that date.

Independent audit, not `/coherence-audit` output. Filed here rather than `docs/`
because its content is internal reasoning — findings, probes, and tradeoffs meant
to inform `specs/backlog.md`, not user-facing guidance.

**Redaction note:** the F1 deep-dive below describes the security-guard bypass
mechanism without the concrete command strings that demonstrate it, per this
repo's rule for a public checkout — the mechanism is the finding, the exploit
string that reproduces it does not go to git. The rest of the document is
otherwise as audited.

## 1. Executive Summary

The codebase has useful architectural boundaries, including agent adapters and explicit hook failure policies, but several implementations undermine those boundaries. The strongest findings concern security-rule bypasses, credential fallback across profiles, and incorrect concurrent state transitions. Complexity is concentrated in orchestration functions; an unused plugin registry adds avoidable maintenance overhead. Evidence: [hook runner](../src/lazy_harness/hooks/runner.py#L156), [agent resolution](../src/lazy_harness/agents/registry.py#L100), and findings below.

**Snapshot:** 10 findings: **0 Critical, 2 High, 7 Medium, 1 Low**. Three principal function-level complexity hotspots identified.

**Method:** Read-only source inspection, reference searches, AST analysis, and targeted probes using mocks or in-memory SQLite. No files changed during the audit; no command payloads or network requests executed. The full test suite was not run. Dependency vulnerability status was not assessed against external advisories. This report was subsequently saved at the user's request.

## 2. Findings Matrix

Paths below are relative to `src/lazy_harness/`.

| ID | Severity | Category | File:Line | Finding Summary | Impact |
|----|----------|----------|-----------|-----------------|--------|
| F1 | High | Security | `hooks/builtins/pre_tool_use_security.py:272` | Whole-command exceptions and incomplete command recognition bypass security rules | Destructive operations escape this guard |
| F2 | High | Security | `core/secrets.py:82` | Failed profile-secret loading preserves inherited credentials | Agent can run under another account |
| F3 | Medium | Complexity | `monitoring/db.py:542` | Delivery acknowledgements do not identify the claimed payload version | Updated telemetry can be marked delivered without transmission |
| F4 | Medium | Security | `cli/metrics_cmd.py:50` | Metrics dry-run still invokes remote delivery | Preview can disclose metadata and modify remote state |
| F5 | Medium | Complexity | `monitoring/sinks/worker.py:44` | Every drain clears retry delays; batch leases can expire during delivery | Repeated retries and overlapping workers |
| F6 | Medium | Security | `core/envrc.py:40` | Paths are interpolated into executable shell text without shell escaping | Special characters become shell syntax |
| F7 | Medium | Complexity | `knowledge/compound_loop.py:919` | Shared memory writes lack coordination across profile workers | Lost updates and temporary-file collisions |
| F8 | Medium | Simplicity / Complexity | `agents/launch.py:62` | Launcher bypasses the existing per-profile agent resolver | Deployment and execution disagree |
| F9 | Medium | Complexity | `hooks/builtins/context_inject.py:729` | Large functions combine orchestration, I/O, state, and presentation | High change coupling and growing runtime cost |
| F10 | Low | Simplicity | `plugins/registry.py:24` | Generic plugin registry has no production callers in this repository | Unused abstraction and misleading architecture comments |

## 3. Deep-Dive Diagnostics

### F1 — Security guard bypasses

**Location:** [pre_tool_use_security.py:272](../src/lazy_harness/hooks/builtins/pre_tool_use_security.py#L272).

**Current Behavior — two distinct mechanisms, each needing its own fix:**

**(a) Whole-command allow-pattern rescue.** Once a blocking rule matches, `should_block` (`:281`) searches every configured allow-pattern against the *entire* command string rather than against the matched destructive substring. A pattern that legitimately needs to rescue one operation (for example, an exception scoped to a specific directory prefix) also rescues anything else chained onto the same command line after a shell separator — the allow-pattern's match anywhere in the string exempts the whole command, destructive operation included. Confirmed with an in-memory probe against `should_block` directly, not reproduced against a live shell.

**(b) Incomplete git command recognition.** The git-specific rules require the subcommand to sit immediately after `git` (whitespace-separated) and, where a rule guards a flag, that flag to sit immediately after the subcommand. See [Git rules](../src/lazy_harness/hooks/builtins/pre_tool_use_security.py#L88). A flag inserted between `git` and its subcommand, or a guarded flag arriving after other arguments instead of directly following the subcommand, does not match either pattern, and the command passes through as abstention rather than denial. Note: a flag that legitimately differs from the blocked one (e.g. the lease-checked variant of a force-push) is correctly let through by design — the rule is scoped to the unchecked variant on purpose, not a gap.

**Architectural Risk:** Exceptions apply beyond the operation they were intended to authorize. Text matching also provides incomplete shell semantics. This establishes a bypass of this hook; it does **not** establish a bypass of any separate agent sandbox or permission system.

### F2 — Credential fallback crosses profile boundaries

**Location:** [secrets.py:82](../src/lazy_harness/core/secrets.py#L82), [launch.py:76](../src/lazy_harness/agents/launch.py#L76).

**Current Behavior:** Launch copies the complete inherited environment. Missing secret files return that environment unchanged; read failures emit a warning and also return it unchanged. A mocked unreadable account-B file preserved account A's `CLAUDE_CODE_OAUTH_TOKEN`.

The continuation is intentional and covered by [test_secrets.py:141](../tests/unit/core/test_secrets.py#L141).

**Architectural Risk:** Availability takes precedence over account identity. When a profile requires different credentials, a provisioning or permission failure can launch authenticated work under the inherited account.

### F3 — Stale acknowledgement loses an updated event

**Location:** [db.py:466](../src/lazy_harness/monitoring/db.py#L466), [db.py:542](../src/lazy_harness/monitoring/db.py#L542).

**Current Behavior:** Re-enqueueing a changed payload replaces its contents and returns the row to `pending`. A worker subsequently acknowledges delivery using only `sink_name` and `event_id`.

An in-memory reproduction confirmed this sequence:

1. Worker claims payload version 1.
2. Ingest replaces it with version 2.
3. Worker acknowledges version 1.
4. The database contains **version 2 with status `sent`**.

**Architectural Risk:** A successful older request can suppress delivery of newer data. Transactional claiming does not protect the later acknowledgement.

### F4 — Metrics dry-run retains external side effects

**Location:** [metrics_cmd.py:50](../src/lazy_harness/cli/metrics_cmd.py#L50).

**Current Behavior:** Dry-run substitutes an in-memory database, but still constructs configured sinks, ingests events, and calls remote `drain()`. A mocked CLI probe confirmed that drain is invoked with `dry_run=True`. The drain performs HTTP POSTs at [worker.py:58](../src/lazy_harness/monitoring/sinks/worker.py#L58).

Payloads include user, tenant, profile, project, session, and host metadata: [ingest.py:205](../src/lazy_harness/monitoring/ingest.py#L205).

**Architectural Risk:** With a remote sink enabled, a preview can transmit metadata and update the collector. The option's help promises only no database writes, but the `dry-run` name conceals a material external side effect.

### F5 — Retry and lease policies conflict with execution

**Location:** [worker.py:44](../src/lazy_harness/monitoring/sinks/worker.py#L44), [db.py:712](../src/lazy_harness/monitoring/db.py#L712).

**Current Behavior:** Every drain clears pending retry timestamps before claiming work. An in-memory probe confirmed that an event delayed for 300 seconds becomes immediately eligible after this reset.

Workers also claim an entire batch under one 60-second lease and send requests sequentially. Defaults permit 50 requests with five-second timeouts: [sink_setup.py:153](../src/lazy_harness/monitoring/sink_setup.py#L153).

**Architectural Risk:** Frequent invocations defeat exponential backoff. Slow batches can outlive their leases, allowing another worker to reclaim unfinished deliveries. Receiver idempotency may limit duplicate records, but cannot eliminate redundant traffic or stale worker acknowledgements.

### F6 — Generated `.envrc` contains executable path syntax

**Location:** [envrc.py:35](../src/lazy_harness/core/envrc.py#L35).

**Current Behavior:** The generator wraps the path in double quotes without escaping shell substitutions or embedded quotes. A pure rendering probe confirmed that a configured path segment containing a command-substitution sequence (`$(...)` or backticks) is emitted verbatim inside the double-quoted export line.

**Architectural Risk:** When sourced, this evaluates the substitution instead of preserving the literal directory name. Exploitation requires influence over the configured path and execution of the generated file; the CLI explicitly instructs users to authorize updated files through `direnv allow`: [profile_cmd.py:280](../src/lazy_harness/cli/profile_cmd.py#L280).

### F7 — Worker locks do not cover shared persistence

**Location:** [compound_loop_worker.py:139](../src/lazy_harness/knowledge/compound_loop_worker.py#L139), [compound_loop.py:919](../src/lazy_harness/knowledge/compound_loop.py#L919).

**Current Behavior:** Workers lock their profile-specific queue. Memory destinations, however, can converge on the same knowledge-store project directory: [memory_store.py:43](../src/lazy_harness/core/memory_store.py#L43).

Writes use a deterministic `.<filename>.tmp`. Proposal updates read the existing document, concatenate, and replace it without a destination lock: [compound_loop.py:1071](../src/lazy_harness/knowledge/compound_loop.py#L1071).

**Architectural Risk:** Two profile workers processing the same project can overwrite each other's changes or collide on the temporary file. Atomic replacement prevents partial visibility; it does not serialize concurrent updates. This is a source-derived race, not a reproduced filesystem failure.

### F8 — Duplicate agent resolution already diverges

**Location:** [launch.py:62](../src/lazy_harness/agents/launch.py#L62).

**Current Behavior:** The launcher selects `cfg.agent.type` directly. The existing [agent_for_profile resolver](../src/lazy_harness/agents/registry.py#L100) honors profile overrides, and [deployment uses it](../src/lazy_harness/deploy/engine.py#L229).

A mocked launch with a Codex profile and global Claude default selected Claude and assigned the Codex profile directory to `CLAUDE_CONFIG_DIR`.

**Architectural Risk:** Configuration generation and execution use different interpretations of the same profile. This is a concrete example of a duplicated policy boundary causing runtime errors. This is not a new item — see `specs/backlog.md` and `docs/roadmap.md` under Theme 5, "Make agent selection per profile throughout."

### F9 — Three orchestration hotspots

**Locations and measurements:**

| Function | Physical lines | AST branch score* |
|---|---:|---:|
| [context_inject.main:729](../src/lazy_harness/hooks/builtins/context_inject.py#L729) | 181 | 44 |
| [overview.render:32](../src/lazy_harness/monitoring/views/overview.py#L32) | 174 | 37 |
| [exec_cmd:319](../src/lazy_harness/cli/exec_cmd.py#L319) | 171 | 35 |

\*A screening heuristic counting branches, Boolean alternatives, handlers, and comprehension generators; not a standardized cognitive-complexity measurement. Physical lines include comments.

**Current Behavior:** These functions combine multiple responsibilities: context collection and rendering; database/filesystem/scheduler inspection and presentation; or launch planning, process management, billing, and result serialization.

The overview additionally retrieves all historical statistics into memory before aggregation: [overview.py:65](../src/lazy_harness/monitoring/views/overview.py#L65), [db.py:400](../src/lazy_harness/monitoring/db.py#L400).

**Architectural Risk:** Changes require reasoning across unrelated failure modes. Overview memory and processing costs grow with retained history.

### F10 — Unused generic plugin infrastructure

**Location:** [plugins/registry.py:24](../src/lazy_harness/plugins/registry.py#L24).

**Current Behavior:** Repository reference searches found callers only in tests. Runtime sink construction explicitly instantiates built-ins and rejects extension sinks: [sink_setup.py:134](../src/lazy_harness/monitoring/sink_setup.py#L134). A comment nevertheless claims that `PluginRegistry` resolves implementation classes: [builtins.py:131](../src/lazy_harness/plugins/builtins.py#L131).

**Architectural Risk:** The repository maintains and tests an extension abstraction that its runtime does not use, while documentation implies otherwise.

## 4. Recommended Best Practices & Action Plan

### Immediate fixes — High

- **F1: Scope exceptions to individual operations.** Normalize supported command forms and require explicit handling of ambiguous shell constructs. Retain native agent permissions or sandboxing as the enforcement boundary. **Tradeoff:** conservative handling increases prompts; robust shell interpretation costs more than regex maintenance.
- **F2: Make credential inheritance explicit.** Distinguish profiles that intentionally inherit credentials from profiles requiring their own. Refuse launch when required credentials cannot load. **Tradeoff:** provisioning failures interrupt launches, but cannot silently switch accounts.

### Medium-term architectural refactors — Simplicity & Complexity

- **F3/F5: Version outbox claims and acknowledgements.** Acknowledge only the claimed revision and lease owner; preserve ordinary retry delays and renew or shorten batch leases. **Tradeoff:** schema migration and additional state, justified by delivery correctness.
- **F4/F6: Close side-effect boundaries.** Prevent remote delivery during dry-run; shell-quote generated path values. Add focused regression cases for both behaviors.
- **F7: Coordinate writes by destination.** Use unique temporary files plus destination-scoped locking around read–modify–write operations. **Tradeoff:** concurrent writers may wait; separate cross-machine coordination is still needed for synchronized stores.
- **F8: Reuse `agent_for_profile` everywhere.** Validate that deployment and launch resolve the same adapter. This removes duplicated policy with little structural cost.
- **F9: Separate collection, decisions, and rendering.** Extract small, concrete helpers and aggregate overview statistics in SQL. **Tradeoff:** more explicit interfaces and queries, balanced against lower memory usage and smaller reasoning units; avoid introducing another generic framework.
- **F10: Remove or defer unused registry infrastructure.** Correct the misleading comment. **Tradeoff:** a future extension feature may require reintroduction, but current runtime behavior remains simpler.
