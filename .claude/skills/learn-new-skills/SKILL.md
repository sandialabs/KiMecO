---
name: learn-new-skills
description: "Create a new agent skill for the KiMecO repository. Use when a task needs a complex, multi-step, repo-specific procedure that will recur (for example submitting a run on HPC, cutting a release, adding a settings keyword) and no skill in .claude/skills/ already covers it, or when the user asks to capture, learn, or document a procedure as a skill. Covers deciding whether a skill is warranted, naming it as an action, writing a trigger-oriented description, grounding every step in code actually read, choosing the operational vs pipeline lane, getting user approval, and writing .claude/skills/<name>/SKILL.md plus a CHANGELOG entry."
---
# Learn new skills

## When to use

Create a skill only when **all** of these hold:

- The procedure is **multi-step** (several commands, files, or checks that must happen in order).
- It is **KiMecO-specific** (depends on this repo's code, templates, settings, CI, or cluster conventions).
- It will **recur** (other agents or the user will need it again).
- **No existing skill** under `.claude/skills/` already covers it.

Do **not** create a skill when the task is a one-off, is generic knowledge (plain git, plain pytest, plain Python), is already spelled out in an agent prompt (`.claude/agents/*.md`), or would only duplicate a wiki page — link the wiki page instead.

## Prerequisites

- Read access to the code, templates, wiki pages, and CI files the procedure touches.
- The user's explicit approval of the drafted skill before anything is written.

## Steps

1. **Check for duplicates.**
   ```bash
   ls .claude/skills/
   grep -ril "<keyword>" .claude/skills/*/SKILL.md
   ```
   If a skill already covers most of the procedure, propose **extending** it instead of creating a new one.
2. **Ground every step.** Read the relevant code, templates (`kimeco/templates/**`), wiki pages (`wiki/*.md`), and CI files (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `hooks/*`) before writing a step. Never invent behaviour: KiMecO only supports Slurm (`q_sys.py` raises `NotImplementedError` for anything else), so never describe PBS/LSF. Anything you could not confirm from the repo must be written as "unverified" in the skill text.
3. **Name it as an action.** Kebab-case verb phrase, at most 64 characters, characters `[a-z0-9-]` only, and the `name` must equal the directory name. Good: `submit-hpc-job`. Bad: `hpc`, `HPC_Jobs`.
4. **Write the description** (YAML quoted string, at most 1024 characters, third person): what the skill does, then `Use when ...` with concrete triggers — commands (`sbatch`, `kmopp`), file names (`input.json`, `KMO_DB_SOP.db`), and exact error strings users will paste.
5. **Write the body** using the template below. Keep it 60–150 lines; put long reference material in the wiki and link it.
6. **Decide on `allowed-tools`.** Only for low-risk, read-only or submit-only commands, and only with the user's explicit consent. Never pre-approve `scancel`, `git push`, `git tag`, or `conda`/`anaconda upload`.
7. **Classify the lane** (see *Lane* below) and state it in the skill.
8. **Present the draft** (name, description, steps, lane, any `allowed-tools`) to the orchestrator, which presents it to the user. Wait for explicit approval.
9. **After approval only**, write `.claude/skills/<name>/SKILL.md` and add an `### Added` bullet under `## Unreleased` in `CHANGELOG.md` (create the `## Unreleased` heading above the latest release if it is missing).
10. **Verify**: re-read both files and confirm the frontmatter parses:
    ```bash
    python -c "import yaml,sys; t=open(sys.argv[1]).read().split('---')[1]; print(yaml.safe_load(t)['name'])" .claude/skills/<name>/SKILL.md
    ```

### Body template

```markdown
---
name: <action-verb-name>
description: "<What it does>. Use when <concrete triggers>."
---
# <Title>
## When to use
## Prerequisites
## Steps            (numbered, exact commands)
## Key files        (paths actually read)
## Checks & pitfalls
## Lane             (operational or pipeline, and why)
```

### Optional preload into an agent

Add the skill to an agent's `skills:` frontmatter list only if that agent uses it on nearly every run. Do it in **both** trees (`.claude/agents/<agent>.md` and `.github/agents/<agent>.agent.md`). Editing agent files is a repository change, so a preload always goes through the pipeline lane.

## Key files

- `.claude/skills/*/SKILL.md` — existing skills.
- `.claude/agents/*.md`, `.github/agents/*.agent.md` — agent prompts and `skills:` preloads.
- `.github/AGENTS.md` — pipeline overview.
- `CHANGELOG.md` — `## Unreleased` section.
- `.gitignore` — ignores only `.ipynb_checkpoints/**`, `**.ipynb`, `**.pyc`, `.DS_Store`, `dev_tests/**`, `.vscode/**`, the local agent files (`CLAUDE.local.md`, `.claude/memory-local/`, `.claude/work/`, `.claude/settings.local.json`) and the coverage outputs (`.coverage`, `htmlcov/`, `coverage.xml`).

## Checks & pitfalls

- Never write a skill file before the user approves the draft.
- Never use `--no-verify` on commits; never weaken tests to make a skill "work".
- Because `.gitignore` is narrow, running KiMecO inside the repo (e.g. `kmo input.json` in `example/`) creates non-ignored paths (`KiMecO.log`, `<project_name>/`). Skills that run KiMecO should recommend a run directory **outside the repository** or under `dev_tests/`.
- Keep facts current: cite file paths and function names so the next reader can re-verify them.

## Lane

- **Operational** — a run of the skill creates or modifies **no git-tracked path** and **no new non-gitignored path** inside the repository. The orchestrator runs it directly with the Skill tool and skips Stages 1–7.
- **Pipeline** — anything else (any write into the repo). Run Stages 1–7.
- Writing a new, user-approved skill file plus its changelog bullet is a bounded exception done by the orchestrator directly.

## Existing skills

| Skill | Purpose | Lane |
| --- | --- | --- |
| `submit-hpc-job` | Submit/monitor `kmo` on Slurm, size resources, triage array jobs | operational (run dir outside repo) |
| `run-tests` | Run the unit suite like the hooks and CI | operational |
| `install-kimeco-env` | Install/repair a conda env with MESS and optional automech | operational |
| `add-settings-keyword` | Add/change an input keyword end-to-end | pipeline |
| `prepare-run-input` | Build `input.json`, MESS, Cantera, CSV inputs | operational if outside repo |
| `restart-or-rescore-run` | Restart or rescore a run from its databases | operational if outside repo |
| `compute-mess-rates` | Run/debug MESS rate computation | operational if outside repo |
| `postprocess-run-results` | `kmopp` extrapolation and `kmoui` dashboard | operational if outside repo |
| `cut-release` | Version bump, changelog finalize, tag prep | pipeline |
| `build-mess-conda-package` | Build/upload the `mess-static` conda package | operational build; recipe edits pipeline |
| `add-dependency` | Add, remove or re-pin a dependency or extra in lockstep | small-fix lane |
| `literature-search` | Find and verify published kinetics/combustion literature | operational (needs `WebSearch`/`WebFetch`, which no pipeline agent holds today) |
| `record-memory-note` | Turn verified facts into tracked or local memory notes and keep the indexes in sync | bounded orchestrator exception (end of chain, "remember" requests) |
| `relabel-mess-by-structure` | Name species from xyz geometry (condensed formula); relabel AutoMech MESS inputs with structure-based names, maps and report (`relabel_mess.py`) | operational (outputs outside repo); script edits pipeline |
| `learn-new-skills` | Create a new skill (this one) | bounded orchestrator exception |

## Backlog candidates

- `add-experiment-type` — new experiment class under `kimeco/experiments/`.
- `add-optimizer` — new optimizer under `kimeco/optimizers/` with its DB prefix.
- `change-db-schema` — runtime writer + `kmoui` reader + migration path, in lockstep.
