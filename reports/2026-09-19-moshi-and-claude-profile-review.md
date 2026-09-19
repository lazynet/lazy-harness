# Moshi and Claude profile review — resolution

Date: 2026-09-19

## Outcome

All six action items from the review are resolved. The Moshi diagnosis now
separates a proven handler defect from an unproven daemon-root hypothesis; the
chezmoi merge preserves both lazy-harness artifact stamps; the profile guide
and ADR-009 describe the deployed write-through ownership model; and ADRs
057–059 decide the three deferred cross-agent questions.

The underlying Moshi/Codex event integration was not reconfigured in this
work. The review asked for the report's causal correction and repair sequence,
not for a live Moshi deployment. No Moshi service was restarted and no usage
data was uploaded.

## Resolution matrix

| Item | Resolution | Evidence |
| --- | --- | --- |
| Moshi daemon-root causal claim | Marked as a hypothesis. The nine `claude-hook` handlers are sufficient to explain missing Codex events; `CODEX_HOME` reaches the service only if a real `codex-hook` event still fails session/transcript resolution. | `lazy-desktop-manager/reports/2026-09-18-moshi-codex-freshness.md` |
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

### dotfiles

- `.chezmoitemplates/lazy-harness/modify-settings.sh`
- `docs/tools/lazy-harness.md`
- `dot_config/lazy-harness/profiles/_common/common.md`

The repository is clean after the automatic commit and push `a17e892`.

### lazy-desktop-manager

- `reports/2026-09-18-moshi-codex-freshness.md`

That report remains untracked, matching its state before this work. The repo
also retains the unrelated untracked Raycast report and its two pre-existing
local commits.

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

### Final gate

All four repository gates passed on the final worktree state:

1. `uv run --frozen pytest -q` — 4991 passed.
2. `uv run --frozen ruff check src tests` — passed.
3. `uv run --frozen ruff format --check src tests` — 492 files already formatted.
4. `uv run --frozen --group docs mkdocs build --strict` — passed.
