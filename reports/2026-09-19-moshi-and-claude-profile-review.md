# Moshi and Claude profile review — resolution

Date: 2026-09-19

## Outcome

All six action items from the review are resolved. The Moshi diagnosis now
separates two proven defects: the wrong hook handler prevented Codex events,
and the daemon's missing `CODEX_HOME` left Chat View unable to read transcripts.
The managed hooks route each dialect correctly and the managed LaunchAgent
resolves the custom Codex root. The chezmoi merge preserves both lazy-harness
artifact stamps, the profile guide and ADR-009 describe the deployed
write-through ownership model, and ADRs 057–059 decide the deferred
cross-agent questions.

## Resolution matrix

| Item | Resolution | Evidence |
| --- | --- | --- |
| Moshi daemon-root causal claim | Kept as a hypothesis until the handler was isolated. A real `codex-hook` event populated Moshi's session cache, but `/v1/transcripts` returned an empty-file cursor. Adding `CODEX_HOME=/Users/lazynet/.codex-lazy` to the daemon changed the same query from 0 lines to 17 lines and 14 entries. | `lazy-desktop-manager/reports/2026-09-18-moshi-codex-freshness.md` |
| Moshi Codex integration | External hooks now dispatch `lazy-codex` through `moshi codex-hook` and Claude profiles through `claude-hook`. Session `01a0ba38-22c6-7020-88e3-c34a1ead6511` appeared in Moshi's cache with the expected metadata, and the corrected daemon streams its rollout to Chat View. | dotfiles config + live probe |
| Codex `features.hooks` advice | Removed as a current requirement. Moshi's warning remains historical evidence; Codex 0.155.0 reports hooks stable and enabled by default. | Same source report |
| `lh_harness_binary` preservation | Added to the shared chezmoi modifier and its tool documentation. The real deploy → apply cycle preserves `lh_version`, `lh_harness_binary`, and the hooks object for lazy and flex. | dotfiles commit `a17e892` |
| `settings.json` ownership | Chose the implementation's existing write-through contract. Adapter config targets are the narrow exception to source immutability; deploy writes the merged document through the runtime symlink into the agent segment. | ADR-009 Evolution + `docs/how/profiles-and-deploy.md` |
| Codex `last_refresh` heuristic | Rejected as an auth verdict. The measured file has no expiry or rejection state, so no age threshold can prove liveness. The current `None` / `n/a` result remains. | ADR-057 |
| Claude Code Keychain `mdat` | Kept operator-only. The Aqua probe proved the metadata useful, but an agent pane also descends from Aqua, so lazy-harness cannot enforce the safe execution boundary and must not invoke `security`. | ADR-058 + ADR-045 Evolution |
| Skills, commands, and agents portability | Skills are the only portable asset class and will be projected into adapter-declared native roots. Reusable commands become skills; native commands and subagent definitions remain in agent segments. Implementation is deferred until a profile-owned skill must run outside Claude Code. | ADR-059 |

## Additional requested cleanup

Removed the stale `vaultkit status` session-start rule from the common profile
segment. The edit was made at the managed destination and persisted with
`chezmoi re-add`; the dotfiles hook committed and pushed it together with the
modifier fix as `a17e892`. Regenerated system docs for lazy, flex, and
lazy-codex contain no `vaultkit` reference, and chezmoi reports no diff for the
common segment.

## Files changed

### lazy-harness worktree

- `docs/how/profiles-and-deploy.md`
- `docs/roadmap.md`
- `specs/adrs/009-profile-symlink-deploy.md`
- `specs/adrs/045-credential-boundary.md`
- `specs/adrs/057-codex-last-refresh-is-not-liveness.md`
- `specs/adrs/058-keychain-mdat-is-operator-only.md`
- `specs/adrs/059-portable-skills-native-commands-agents.md`
- `specs/adrs/README.md`
- `specs/backlog.md`
- `specs/designs/codex-evidence.md`

Worktree: `.worktrees/profile-coherence-fixes`

Branch: `fix/profile-coherence-fixes`

Pull request: https://github.com/lazynet/lazy-harness/pull/406

The PR contains the review resolution plus report-only verification follow-ups.

### dotfiles

- `.chezmoitemplates/lazy-harness/modify-settings.sh`
- `docs/tools/lazy-harness.md`
- `dot_config/lazy-harness/config.toml.tmpl`
- `dot_config/lazy-harness/profiles/_common/common.md`
- `dot_local/bin/executable_moshi-hook-update`
- `private_Library/LaunchAgents/sh.brew.moshi-hook.plist`

The first three review fixes were committed and pushed automatically as
`a17e892`; the Moshi dialect router is `6186144`, and the persistent Chat View
daemon fix is `99c0664`.

### lazy-desktop-manager

- `reports/2026-09-18-moshi-codex-freshness.md`

The diagnosis correction was committed separately as `21004d7`; the live
event verification is `c2326a4`, and the Chat View root-cause correction is
`440c980`. The unrelated untracked reports and pre-existing local commits were
left untouched.

## Verification

- `lh deploy --profile lazy`: passed.
- `lh deploy --profile flex`: passed.
- Target/source byte equality for both `settings.json` files: passed.
- `jq` assertion for `lh_version == "0.74.0"`,
  `lh_harness_binary == "lh"`, and an object-valued hooks block: passed for
  both profiles after deploy → apply.
- `chezmoi diff` for both profile settings and the common segment: empty.
- Search for `vaultkit` across deployed profiles and dotfiles profile source:
  no matches.
- `uv run --frozen ruff check src tests`: passed.
- `uv run --frozen ruff format --check src tests`: passed, 492 files already
  formatted.
- `uv run --frozen --group docs mkdocs build --strict`: passed after the final
  ADR cross-links.
- `uv run --frozen pytest -q tests/docs`: passed, 47 tests.
- `uv run --frozen pytest -q`: passed, 4991 tests in 465.54 seconds.
- Deployed Moshi routing: all nine `lazy-codex` entries resolve to
  `moshi codex-hook`; lazy and flex resolve to `moshi claude-hook` without the
  stale duplicate entries.
- Codex hook trust review: 9 modified Moshi hooks approved; every installed
  lifecycle hook then reported active.
- Live read-only probe: `MOSHI_PROBE_TRUSTED` completed in session
  `01a0ba38-22c6-7020-88e3-c34a1ead6511`; Moshi created the matching
  `codex-sessions` record at 12:12 with current session and Herdr metadata.
- Chat View isolation: before the daemon environment fix, the transcript
  WebSocket opened but returned `totalLines: 0` with the SHA-256 digest of an
  empty file. The rollout itself existed and contained the probe exchange.
- Daemon root: the managed LaunchAgent now exports
  `CODEX_HOME=/Users/lazynet/.codex-lazy`. After reload, the same transcript
  query returned `totalLines: 17`, `entryCount: 14`, and `hasMore: true`.
- Moshi service after reload: `running: true`, `gateway: true`.
- iPhone acceptance test: after reopening the terminal following the gateway
  reload, the user confirmed that the Codex agent and Chat View render
  correctly in the Moshi client.

### Final gate

All four repository gates passed on the final worktree state:

1. `uv run --frozen pytest -q` — 4991 passed.
2. `uv run --frozen ruff check src tests` — passed.
3. `uv run --frozen ruff format --check src tests` — 492 files already formatted.
4. `uv run --frozen --group docs mkdocs build --strict` — passed.

## Live Moshi probe

The user explicitly approved one read-only Codex prompt and the associated
hook egress to `api.getmoshi.app`. The first non-interactive attempt ran before
the modified hook hashes were trusted and therefore emitted no Moshi record.
After reviewing and trusting the nine generated Moshi hooks, the effective
probe completed and produced a current record under Moshi's `codex-sessions`
cache.

The record contains the Codex model, first and last prompt timestamps, prompt
kind and sequence, process ID, and Herdr pane/workspace mapping. That closed
the event-handler repair, but the iPhone then exposed the independent Chat
View failure: the gateway mapped the session and opened the correct endpoint,
yet returned an empty transcript because its service environment used the
default Codex root.

The LaunchAgent now exports the custom root and is managed by chezmoi. The
daily Moshi updater reapplies that plist after Homebrew regenerates it, then
reloads the service. The corrected gateway reads the existing rollout without
another prompt. Usage collection remains disabled; this change did not opt the
machine into background usage polling.
