# Portable repository instructions design

**Status:** proposed  
**Date:** 2026-09-19  
**Decision:** [ADR-060](../adrs/060-agents-md-is-the-portable-repository-contract.md)

## Problem

The repository fleet grew around `CLAUDE.md`. Codex loads `AGENTS.md`, while
Claude Code can share it through an import. Copying rules into both files
creates two truths; lazy-harness's current inverse shim keeps Claude-specific
syntax canonical.

Wave 0 found 14 owned repositories: eleven carry only `CLAUDE.md`, lazy-harness
carries both with the inverse shim, and two carry neither. The first migration
batch is lazy-harness, lazy-ai-tools and dotfiles.

## Contract

`AGENTS.md` is canonical and contains runtime-neutral language, scope,
verification, layout, safety and contribution rules. `CLAUDE.md` starts with
`@AGENTS.md`, then contains only Claude-specific commands, tools or lifecycle
details. It never copies shared paragraphs.

Nested files keep closest-file precedence: a nested `CLAUDE.md` imports its
sibling `AGENTS.md`. Generated profile system documents remain separate.

This uses the documented discovery/import contracts:

- <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- <https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools>

## Migration algorithm

For each repository in an explicit manifest:

1. classify current lines as portable, Claude-only, obsolete or local;
2. move portable content to `AGENTS.md` without changing meaning;
3. replace shared content in `CLAUDE.md` with the import;
4. probe both installed agents from the root and one nested directory;
5. run the repository's existing verification gate before committing.

Wave 1 keeps this manual. Repositories with neither file are inventoried, not
populated without repository-specific rules.

## Gates and rollout

- A static check rejects duplicated non-heading paragraphs and missing or late
  imports.
- Runtime probes prove both agents see one sentinel from root and nested paths.
- Claude Code installations that cannot import are unsupported; content is not
  forked for them.
- The three pilots run for seven working days without restoring shared rules
  to `CLAUDE.md` before Wave 2 migrates the remaining repositories.

Rollback restores the prior pair from Git. ADR-059's skill projection is a
coordinated but separate lane: profile-owned executable guidance is not a
repository instruction file.

