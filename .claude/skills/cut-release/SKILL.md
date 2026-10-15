---
name: cut-release
description: "Cut a KiMecO release: bump the SemVer version, finalize CHANGELOG.md, and prepare the tag. Use when the user asks to release, bump the version, publish a version, or tag. Thin checklist that defers to the 'Release cuts' section of .claude/agents/version-control.md as the source of truth; committing, tagging, and pushing happen only with explicit user approval."
---
# Cut a release

## When to use

The user asks to release, bump the version, or tag. This skill is a checklist; the policy lives in `.claude/agents/version-control.md`.

## Prerequisites

- Read the **"Release cuts (only on explicit user request/approval)"** section and the "Constraints and Invariants" section of `.claude/agents/version-control.md` first. If anything below disagrees with it, that file wins.
- A non-empty `## [Unreleased]` section in `CHANGELOG.md`.
- The user's explicit choice of version number.

## Steps

1. **Find the current version** (must be identical in all three; there is no `__version__` in the package):
   ```bash
   grep -n '^version' pyproject.toml
   grep -n "^VERSION" setup.py
   grep -n 'set version' meta.yaml
   ```
2. **Propose the SemVer bump** from `[Unreleased]` (`Added`/`Changed` → minor, only `Fixed` → patch, breaking → major) and let the user decide.
3. **Run the suite** (see `run-tests`): `python -m pytest tests/unit/ -q`. Do not cut a release on red tests.
4. **Edit `CHANGELOG.md`**:
   - rename `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD`;
   - insert a fresh empty `## [Unreleased]` above it;
   - footer: add `[x.y.z]: https://github.com/sandialabs/KiMecO/compare/vPREV...vx.y.z` and change `[Unreleased]: .../compare/vPREV...HEAD` to `.../compare/vx.y.z...HEAD`.
   Example for a `1.1.7` → `1.2.0` cut, footer after the edit:
   ```text
   [1.2.0]: https://github.com/sandialabs/KiMecO/compare/v1.1.7...v1.2.0
   [1.1.7]: https://github.com/sandialabs/KiMecO/compare/v1.1.6...v1.1.7
   ...
   [Unreleased]: https://github.com/sandialabs/KiMecO/compare/v1.2.0...HEAD
   ```
   The version links sit at the bottom of the file, newest first, with `[Unreleased]` last.
5. **Bump the version** identically in `pyproject.toml` (`version = "x.y.z"`), `setup.py` (`VERSION = 'x.y.z'`), and `meta.yaml` (`{% set version = "x.y.z" %}`). Do not touch `conda-recipes/mess-static/meta.yaml` (separate package, see `build-mess-conda-package`).
6. **Re-read** all four files and confirm the version strings match.
7. **Stop and report** the edited-but-uncommitted files. Only on an explicit, user-approved instruction relayed by the orchestrator, follow the commit/merge/tag steps of `version-control.md` (commit on the development branch, `--no-ff` merge into `main`, annotated tag `vx.y.z` on the merge commit). The branch names and merge flow are defined there; if the repository's branches do not match that description, ask the user.
8. **Pushing** (`git push`, `git push --tags`) needs a separate explicit approval.

## Key files

- `.claude/agents/version-control.md` (source of truth)
- `CHANGELOG.md`, `pyproject.toml`, `setup.py`, `meta.yaml`
- `.github/workflows/publish-wiki.yml` — mirrors `wiki/` to the GitHub Wiki on push to `main` when `wiki/**` changes.

## Checks & pitfalls

- Never use `--no-verify`; the pre-commit/pre-push hooks run the unit tests.
- Never force-push, amend published commits, or delete tags without explicit confirmation.
- Never tag a commit that is not the release merge commit.
- Keep the Keep-a-Changelog format: sections `### Added`, `### Changed`, `### Fixed`, `### Removed`.
- Released `CHANGELOG.md` sections are history: do not rewrite them while cutting a new release.

## Lane

Pipeline: it edits tracked files (changelog and version strings), owned by the `version-control` agent.
