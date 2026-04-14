# ADR-003: TOML as the single config format

**Status:** accepted
**Date:** 2026-04-12

## Context

The framework needs one config file that lives in a predictable place and is edited by humans. It must support:

- Nested sections (profiles, hooks per event, knowledge subsystems, monitoring, scheduler jobs)
- Inline comments, because the users of this tool will want to annotate their own choices
- Parsing with zero external dependencies — the config loader is on the hot path of every `lh` invocation, and pulling in a heavy parser just to start the CLI is unacceptable
- Round-tripping: `lh init` and `lh migrate` write config too, not only read it

## Decision

TOML as the single canonical format. One file: `~/.config/lazy-harness/config.toml` (overridable with `LH_CONFIG_DIR`).

- **Reading:** `tomllib` from the Python standard library (Python 3.11+). No runtime dependency.
- **Writing:** `tomli-w`, a single small dependency used only by `lh init` and the migration executor.
- **Validation:** explicit dataclasses in `src/lazy_harness/core/config.py`. Each section has its own dataclass with typed fields and defaults; the loader raises `ConfigError` with the exact path and key on any parse failure.
- **No config DSL, no templating.** The file is literally the TOML the user sees. There is no pre-processor, no environment variable expansion inside the file (env vars are expanded by `core/paths.py` when a path is actually used), no include directives.

## Alternatives considered

- **YAML.** Forces `PyYAML` as a dependency and brings its footguns with it: the Norway problem, implicit-type coercion, significant whitespace bugs in hand-edited files. Rejected because the failure modes are silent — you do not find out until a hook misbehaves.
- **JSON.** No comments. A config file you cannot annotate is a config file users will not understand. Rejected for human-edited config; `settings.json` inside each Claude Code profile is still JSON because Claude Code itself requires it, but that is a generated file and no human is meant to maintain it by hand.
- **INI.** No real nested structure, only sections and keys. Insufficient for nested profile entries like `[profiles.work]` + `config_dir`/`roots`/`lazynorth_doc` without arbitrary flattening conventions. Rejected.
- **Python file as config.** Zero parsing cost, infinite expressivity — and infinite foot-guns. A config file that can import arbitrary code is a config file that can break at startup in ways a text-only loader cannot. Rejected.
- **Multiple files, one per concern.** `profiles.toml`, `hooks.toml`, `monitoring.toml`. Tempting for the author, painful for the user: you have to open four files to understand one setup. Rejected.

## Consequences

- The config path is trivial to explain: one TOML file, one dataclass per section, one `load_config()` entry point. Everything else in the codebase consumes `Config`.
- No third-party parser on the read path means the CLI starts fast and never fails because of a dependency pin.
- Writing config is opt-in: only `lh init`, `lh migrate`, and `lh profile add` ever call `save_config`. Normal operation never rewrites the user's file, which means users can trust that their comments and formatting survive.
- Adding a new feature that needs configuration = adding a dataclass section and a loader branch. No schema file, no JSON schema, no migration system for config shape yet. If config shape changes incompatibly, we bump `[harness].version` and the migration engine handles the transition.
- The loader explicitly rejects a missing `[harness].version` field. This is the version anchor — without it we cannot safely migrate shape changes in the future.
