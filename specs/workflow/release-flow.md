# Release flow

Versions are managed by **release-please** (`.github/workflows/release-please.yml`). Do **not** bump `pyproject.toml` or `src/lazy_harness/__init__.py` by hand, and do **not** create `vX.Y.Z` tags manually.

## How it works

On every push to `main`, release-please:

1. Scans commits since the last release.
2. Decides the next version from the conventional-commit types present:
   - `feat:` → **minor** bump
   - `fix:` → **patch** bump
   - `BREAKING CHANGE:` in the commit footer (or a `!` after the type, e.g. `feat!:`) → **major** bump
   - `chore:`, `ci:`, `test:`, `docs:`, `refactor:` → no bump; hidden from the changelog by default
3. Opens a PR titled `chore(main): release X.Y.Z` containing:
   - The version bump in both `pyproject.toml` and `src/lazy_harness/__init__.py`
   - A `CHANGELOG.md` entry grouped by section
   - Nothing else

**Merging that PR is the release.** release-please then creates the `vX.Y.Z` tag and a GitHub Release automatically.

## What this means in practice

- **Use conventional-commit prefixes rigorously.** A single merged `fix:` triggers a patch bump; a single `feat:` triggers a minor bump. Mislabeling a bug fix as `feat:` silently makes the next release a minor bump when it should have been a patch.
- **`BREAKING CHANGE:` is for actual user-visible breakage.** Renaming an internal helper is not breaking. Removing a CLI flag is. Use sparingly.
- **Edit the release PR in place when needed.** If the changelog has a typo or is missing context, push commits to the release PR branch directly. release-please re-opens the same PR rather than duplicating.
- **The docs site still redeploys on every push.** `.github/workflows/docs.yml` runs on push to `main`, independently. A release merge is just another push from its perspective.

## Version synchronisation invariant

Both files are kept in sync by release-please:

- `pyproject.toml` → `[project].version`
- `src/lazy_harness/__init__.py` → `__version__` line with the `x-release-please-version` marker

`tests/unit/test_version.py` guards the invariant that the two files never drift. If you ever see them disagree, a manual edit slipped through — fix by reverting the manual edit, not by patching both files.

## What you should never do

- **Never** hand-edit `[project].version` or `__version__`. release-please owns both.
- **Never** tag `vX.Y.Z` manually. release-please creates the tag.
- **Never** delete or force-push the release PR. If it looks wrong, push a fix commit to its branch; release-please will update.
