# Portable repository instructions design

**Status:** proposed  
**Date:** 2026-09-19  
**Decision:** [ADR-060](../adrs/060-agents-md-is-the-portable-repository-contract.md)

## Problem

The repository fleet grew around `CLAUDE.md`. Both target runtimes load
`AGENTS.md`, but a `CLAUDE.md` causes Claude Code to prefer that surface and
breaks portable parent-chain discovery. Copying rules creates two truths;
imports fail when the importing file comes from a parent directory.

Wave 0 found 14 owned repositories: eleven carry only `CLAUDE.md`, lazy-harness
carries both with the inverse shim, and two carry neither. The first migration
batch is lazy-harness, lazy-ai-tools and dotfiles.

## Contract

`AGENTS.md` is the only repository instruction surface and contains scope,
verification, layout, safety and contribution rules. Runtime-specific commands,
tools or lifecycle details live in labelled conditional sections. `CLAUDE.md`
is rejected because it shadows direct `AGENTS.md` discovery.

Nested `AGENTS.md` files keep closest-file precedence. Generated profile system
documents remain separate.

This uses the documented discovery/import contracts:

- <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- <https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools>

## Migration algorithm

For each repository in an explicit manifest:

1. classify current lines as portable, Claude-only, obsolete or local;
2. move portable content to `AGENTS.md` without changing meaning;
3. move runtime-specific content into labelled `AGENTS.md` sections and remove
   `CLAUDE.md`;
4. probe both installed agents from the root and one nested directory;
5. run the repository's existing verification gate before committing.

Wave 1 keeps this manual. Repositories with neither file are inventoried, not
populated without repository-specific rules.

lazy-harness is migrated as of 2026-09-19; lazy-ai-tools and dotfiles are not.
The remaining pilot work and the seven-day observation are tracked in
`specs/backlog.md` — the horizon is an observation with an opening date, not an
implemented check.

## Gates and rollout

- A static check rejects a missing root `AGENTS.md` and every `CLAUDE.md` that
  would shadow it. Implemented as `lh repo instructions`
  (`src/lazy_harness/core/repo_instructions.py`), which takes any path, and run
  against this repository by `tests/docs/test_repo_instructions_gate.py`.
- Runtime probes prove both agents see one sentinel from root and nested paths.
  The original import design failed nested Claude Code sessions; direct
  `AGENTS.md` loading passed the nested probe and is the shipped contract.
  Ten runs, spelling controls and the rejected alternatives are in
  [repo-instruction-discovery-evidence.md](repo-instruction-discovery-evidence.md);
  the pilot ships without `CLAUDE.md`.
- The three pilots run for seven working days without restoring shared rules
  to `CLAUDE.md` before Wave 2 migrates the remaining repositories.

Rollback restores the prior pair from Git. ADR-059's skill projection is a
coordinated but separate lane: profile-owned executable guidance is not a
repository instruction file.
