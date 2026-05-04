# ADR-028: Configurable session classification rules

**Status:** accepted
**Date:** 2026-05-03

## Context

`session_export._classify(cwd)` ([ADR-011](./011-session-export-and-classification.md)) returns the `(profile, session_type)` pair written into every exported session's frontmatter. The implementation has been hardcoded since the bash predecessor:

```python
if "lazymind" in lower or "obsidian" in lower:  return ("personal", "vault")
if "/repos/lazy/" in cwd:                        return ("personal", "personal")
if "/repos/flex/" in cwd:                        return ("work", "work")
return ("other", "other")
```

The literals match the maintainer's directory layout. For any other user, every session falls through to `("other", "other")`, so `session_type` carries no information and the per-profile filter on `lh status sessions --profile X` produces nothing useful for them. The classification feature is, in practice, broken outside of one machine.

Two competing constraints shape the fix:

1. The framework is public OSS and should not ship behaviour that only works for the maintainer's setup ([feedback rule, 2026-05-03](../../README.md): no personal setup in public surface).
2. The maintainer has a sizeable archive of historical session exports indexed in QMD with `session_type: personal` / `session_type: work` / `session_type: vault`. Changing the values produced by the same `cwd` would split the archive: old exports keep the old classification, new exports get a different one, and any saved query that filters on `session_type` breaks for sessions going forward.

A naive "use `resolve_profile()` for both fields" rewrite satisfies (1) and breaks (2).

## Decision

**Lift the four hardcoded rules into a typed config field `[knowledge].classify_rules`, with a default value that reproduces the current behaviour bit-for-bit. `_classify(cwd, rules)` becomes a pure data-driven function over the rules list. `export_session(...)` accepts the rules via an optional argument; the `session-export` builtin hook passes `cfg.knowledge.classify_rules` from the loaded config.**

Concretely:

- `core/config.py` gains a `ClassifyRule` dataclass with three fields: `pattern: str`, `profile: str`, `session_type: str`. `KnowledgeConfig.classify_rules: list[ClassifyRule]` defaults to the four current rules in their current order.
- The TOML reader accepts `[[knowledge.classify_rules]]` arrays-of-tables; absence of the section yields the default list, not an empty list. Explicit empty list (`classify_rules = []`) overrides the default — no rule matches, every session classifies as `("other", "other")`.
- `session_export._classify` becomes `_classify(cwd: str, rules: list[ClassifyRule]) -> tuple[str, str]`. It returns the first matching rule's `(profile, session_type)`, or `("other", "other")` if none matches. Matching is the existing case-insensitive substring check.
- `session_export.export_session(...)` gains an optional `classify_rules` parameter (default `None` → uses the dataclass default list, preserving direct callers that do not load config).
- `hooks/builtins/session_export.py` (the only production caller) passes `cfg.knowledge.classify_rules` from the loaded config — the call site already has `cfg`.

The defaults make the change a no-op for the maintainer: the same `cwd` produces the same `(profile, session_type)`. QMD queries already saved against `session_type: personal` keep working for new exports just as they did for old ones.

## Alternatives considered

- **Replace `_classify` entirely with `(resolve_profile(cwd), inferred_type)`.** Cleanest from a code-hygiene perspective and has the right shape long-term, but breaks the maintainer's QMD archive: the same `cwd` that produced `session_type: personal` yesterday would produce `session_type: code` tomorrow. Rejected for breaking downstream consumers without warning.
- **Keep the hardcoded rules and accept the bug for non-maintainer users.** Documented honestly, this would be tolerable, but it conflicts with the public-OSS framing and with [ADR-001](./001-hybrid-architecture.md)'s separation between framework code (no personal content) and user dotfiles (where personal content belongs).
- **Use a single map `cwd_pattern -> (profile, session_type)` in TOML.** Slightly cheaper to write, but TOML inline tables disallow keys with `/`, which our patterns need. The arrays-of-tables shape is verbose but unambiguous and round-trips through `tomli_w`.
- **Move the rules into the user's profile entries (`[profiles.personal].classify_patterns = [...]`).** Ties classification to profile resolution in a way that conflates two concerns: which target dir a session writes to (profile resolution) versus how it is labelled in the export (classification). Rejected — the deploy-side use of `[profiles]` already has enough surface; classification is an export-side concern and belongs under `[knowledge]`.
- **Make `session_type` derive from `resolve_profile()` plus a `vault_dir` config field.** Cleaner long-term, but still produces different values for the same `cwd` than today (`code` instead of `personal`). The configurable-rules approach gets us to "no hardcoded personal paths in source" without that breakage; a future ADR can deprecate the rule list once the archive concern lapses.

## Consequences

- **No behaviour change for the maintainer.** Defaults are byte-equivalent to the prior hardcoded check; existing tests continue to pass without modification of their assertions.
- **Other users get a useful classification.** They drop a `[[knowledge.classify_rules]]` entry per directory pattern they care about and get sensible `session_type` values in their exports.
- **No personal paths in source.** `src/lazy_harness/knowledge/session_export.py` no longer mentions `repos/lazy` or `repos/flex` as literals. The literals appear once, as the default value of a config field in `core/config.py`, framed explicitly as "the maintainer's setup; override via `[knowledge.classify_rules]`".
- **One new config surface.** Documented in `docs/how/knowledge-pipeline.md` and `docs/reference/config.md`. `lh config knowledge --init` (ADR-026) does not change today; a follow-up may add a wizard step for classify rules.
- **Tests for the new path live alongside the old ones** in `tests/unit/test_session_export.py`. The new tests use abstract patterns (`"/foo/"`) and abstract `cwd` strings, not real directory layouts — keeping the test fixtures free of personal paths is part of the same hygiene goal.
- **`ClassifyRule` is a thin dataclass, not a class with methods.** Matching logic stays inside `_classify` so the rule type is purely declarative — a step away from re-introducing complexity at the data layer.
- **Migration path for the maintainer is empty:** no config edit required, no export reformat, nothing to roll back. The defaults are the migration.
