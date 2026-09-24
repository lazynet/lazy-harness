# Claude Code dialect evidence — caller identification marker

**Status:** one probe recorded, 2026-09-24, against Claude Code 2.1.281.
**Scope:** this note owns one fact only — the payload key `hooks/runner.py`'s
`_caller_agent` uses to tell a Claude Code hook invocation apart from a Codex
one (ADR-041, Evolution 2026-09-24; ADR-068, Evolution 2026-09-24). It is not
a full dialect probe in the shape of `specs/designs/codex-evidence.md`; it
states only what the runner docstring and `tests/unit/hooks/test_runner.py`
already record as observed, with no new probe run to produce it.

## Observed

**Claude Code 2.1.281 dump-hook probe, 2026-09-24.** A `PreToolUse` payload
sends `prompt_id` and does not send `turn_id` or `model`. Recorded in
`hooks/runner.py:93-99` (`_CALLER_MARKERS` docstring) and mirrored in
`tests/unit/hooks/test_runner.py:30-40` (`CLAUDE_PRE_TOOL_USE` fixture).

Contrast, for the same marker on the other side: Codex 0.154.0 sends
`turn_id` and `model` and no `prompt_id`, on `PreToolUse` — `specs/designs/
codex-evidence.md` §1, probe 5.

**What was not measured.** The probe covers `PreToolUse` only. The runner
docstring is explicit that other Claude Code events were not measured for
these markers, so `_caller_agent` cannot tell a caller apart on those events
either — an unidentified caller on an unknown profile refuses rather than
guesses (`hooks/runner.py:103`, `_fallback_profile`).
