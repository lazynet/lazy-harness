# ADR-005: XDG-first path resolution with explicit overrides

**Status:** accepted
**Date:** 2026-04-13

## Context

Every subsystem — config loader, hook engine, deploy engine, migration steps — needs to know where lazy-harness stores things. Hardcoding `~/.config/lazy-harness/` works on one developer's machine and breaks under:

- A user with `XDG_CONFIG_HOME` set to a non-default location (common on Linux).
- A user on Windows, where `%APPDATA%` and `%LOCALAPPDATA%` are the conventional locations.
- A test suite that needs isolated config/data/cache directories without touching the real user home.
- A `chezmoi`-managed dotfile setup that wants to point lazy-harness at a staging directory during template rendering.

Ad-hoc `os.path.expanduser("~/.config/lazy-harness")` calls scattered across modules make all of these impossible without a find-and-replace.

## Decision

Single path module at `src/lazy_harness/core/paths.py`. Three public functions — `config_dir()`, `data_dir()`, `cache_dir()` — and a helper `config_file()` that returns `config_dir() / "config.toml"`. Nothing else in the codebase computes these paths.

Resolution order, applied identically in each function:

1. **Explicit override env var** — `LH_CONFIG_DIR`, `LH_DATA_DIR`, `LH_CACHE_DIR`. If set, used verbatim. This is the test-suite and CI hatch.
2. **XDG base directory env vars** — `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`. If set, the lazy-harness subdirectory is appended (`$XDG_CONFIG_HOME/lazy-harness`).
3. **Platform default** — on macOS and Linux: `~/.config/lazy-harness`, `~/.local/share/lazy-harness`, `~/.cache/lazy-harness`. On Windows: `%APPDATA%\lazy-harness`, `%LOCALAPPDATA%\lazy-harness`, `%LOCALAPPDATA%\lazy-harness\cache`.

Path expansion (`~` → home) and resolution (relative → absolute) are centralized in `expand_path()` and `contract_path()`, used wherever a user-supplied path enters the system.

## Alternatives considered

- **Hardcoded `~/.config/lazy-harness/` only.** Unportable to Windows and untestable without mocking `Path.home()`. Rejected.
- **`platformdirs` library.** Exactly the abstraction we want — and a third-party dependency on the CLI hot path for something we can write in 90 lines. Rejected on the "every dependency earns its keep" principle; if `platformdirs` grows features we want later we can reconsider.
- **Always XDG on every platform.** Linux convention, inconvenient on Windows where `%APPDATA%` is expected by other tools. Rejected.
- **A single `LH_HOME` override instead of three.** Collapses config/data/cache into one directory, which breaks XDG's separation-of-concerns (config is user-edited, data is program-managed, cache is disposable). Rejected.

## Consequences

- One import (`from lazy_harness.core.paths import config_dir, config_file, ...`) is the single source of truth for locations. A grep for any other path computation is a lint-level smell.
- The three `LH_*` env vars make the test suite trivially isolated: every test that touches the filesystem sets them to a `tmp_path` fixture and the rest of the code needs no modification.
- Windows support is latent but real. The logic is implemented; platform-specific CI to prove it will come when we have a user asking for it.
- Migration from non-XDG layouts is explicit: `lh migrate` reads paths from the predecessor installation and writes them into `config.toml` as user-facing settings. The path module never auto-migrates state on the user's behalf.
- The resolution order is prioritized so that "make it work in this test / make it work in this sandbox" is a single env-var export rather than a code path.
