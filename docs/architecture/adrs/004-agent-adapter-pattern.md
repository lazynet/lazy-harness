# ADR-004: Agent Adapter Pattern

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-harness is designed to support multiple AI coding agents. v1 only supports Claude Code, but the architecture must allow adding agents without restructuring.

## Decision

Python Protocol-based adapter pattern. Each agent implements `AgentAdapter` protocol: config dir resolution, session parsing, hook support, and hook config generation. A registry maps `config.toml`'s `[agent].type` to the adapter.

## Alternatives Considered

- **Agent-specific code throughout:** Fast for one agent, rewrite for each new one.
- **Plugin-only agents:** Too much indirection for v1. Adapters are simpler.

## Consequences

- Adding a new agent = implementing the protocol + registering it.
- Core framework code never references agent-specific details.
- The protocol is minimal — only what the framework actually needs from agents.
