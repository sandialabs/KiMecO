# Agentic Delivery Pipeline for GAME / KiMecO

Every change request flows through a single **seven-stage pipeline**, driven by the user-invocable **Workflow Orchestrator**. The orchestrator is the only agent that talks to the user; the seven stage agents run as subagents and return their output to it. Requests fully handled by an **operational-lane** skill run (one that writes nothing git-tracked and no non-gitignored new path in the repo) are run directly by the orchestrator and bypass the stages; see *Loop and gate rules*.

## Pipeline

```
User request
   │
   ▼
Workflow Orchestrator  ──drives──► 1. Scope Assessment ─┐
   ▲                                                    │
   │                               2. Specification Review
   │                                                    │
   │                       NEEDS_INPUT ◄────────────────┤
   │                               3. Clarification ─────┘   (loop 1→2→3 until COMPLETE)
   │                                                    │
   │                                          COMPLETE  ▼
   │                               4. Boundary Definition  (modify vs freeze → user validates)
   │                                                    │
   │                               5. Design (in parallel):
   │                                    ├─ Planning  (plan design, Phase A)
   │                                    └─ CI Test   (test design)
   │                                        → user confirms plan + tests together
   │                                                    │
   │                               6. Implement + run tests:
   │                                    ├─ Planning  (implement, in bounds)
   │                                    └─ CI Test   (author + run tests)
   │                                                    │
   │                               7. Version Control  (changelog + wiki + manual)
   ▼
Summary to user
```

## Stages

| # | Agent (`*.agent.md`) | Role | Tools | User-invocable |
| --- | --- | --- | --- | --- |
| — | `workflow-orchestrator` | Entry point. Drives the loop, is the sole user-facing agent, dispatches all stages; runs operational-lane skills directly and writes user-approved new skills. | read, search, edit, execute, agent, todo, skill | yes |
| 1 | `scope-assessment` | Exhaustively determines every system concerned (backend, config, DB, GUIs) and ripple effects. Must not miss anything. | read, search | no |
| 2 | `spec-review` | Gatekeeper: decides `COMPLETE` vs `NEEDS_INPUT` (ambiguity / missing decisions). | read, search | no |
| 3 | `clarification` | Turns Stage 2 gaps into precise questions with concrete options for the user. | read, search | no |
| 4 | `boundaries` | Defines the safe **modify zone** vs **freeze zone**; **user validates** before planning. | read, search | no |
| 5 | `planning` ∥ `ci-test` | **Plan design and test design run in parallel** from the same spec + boundaries; user confirms both together before any code is written. | read, search, edit, execute, todo, skill | no |
| 6 | `planning` → `ci-test` | `planning` implements inside the boundaries, then `ci-test` authors + runs the designed tests. | read, search, edit, execute, todo, skill | no |
| 7 | `version-control` | Updates `CHANGELOG.md`, the wiki (`wiki/**`), and the manual (`MANUAL.md`); handles release cuts on approval. | read, search, edit, execute, todo, skill | yes |

## Loop and gate rules

- Stages 1→2→3 repeat until Stage 2 returns `STATUS: COMPLETE`. Every clarification answer re-enters at Stage 1 (re-assess scope on the enriched spec).
- Boundary definition (Stage 4) begins only after `COMPLETE` (or an explicit user "proceed as-is").
- Stage 5 runs **plan design (`planning` Phase A) and test design (`ci-test`) in parallel** from the same validated boundaries; the user confirms the combined plan + test design before any code is written.
- Stage 6 is sequential: `planning` implements strictly inside the validated modify zone, then `ci-test` authors and runs the designed tests. Stage 6 begins only after the Stage 5c confirmation.
- The user is still asked for a preferred test before Stage 5 test design begins.
- Stages run in order 1–3 → 4 → 5 → 6 → 7; only the two Stage-5 design tasks run concurrently. Exception: an **operational-lane** skill run — one that creates or modifies no git-tracked path and no non-gitignored new path in the repository (e.g. `submit-hpc-job`, `postprocess-run-results`) — is executed directly by the orchestrator and skips Stages 1–7; any skill run that writes into the repository goes through the pipeline.

## User-interaction model

- The orchestrator owns all direct user interaction. Stage agents produce the *content* of questions (Stage 3), boundary proposals (Stage 4), plans and test designs (Stage 5); the orchestrator presents them and feeds answers back down.
- Subagent results are not visible to the user — the orchestrator relays every question, boundary set, plan, and summary in its own message.
- New skills (`.claude/skills/<name>/SKILL.md`) are proposed via the `learn-new-skills` skill: the orchestrator presents the drafted name, description, and steps to the user and, only after explicit approval, writes the skill file and its `CHANGELOG.md` `[Unreleased]` entry itself, then re-reads them to verify.

## Shared invariants (enforced by Stages 1/4/5)

- A keyword/setting change ripples to `default_settings.py` + `user_input.py` + every consumer + the `kmo_start` GUI.
- A DB schema change updates runtime writers and `kmoui` readers in lockstep, with a migration path.
- SOP / RateCo / SIM contract changes are coordinated across chemistry, model, HPC, database, and GUI.
- `ModelStatus` / `JobStatus` transitions stay valid and monotonic; GOAT indexing/`Scoring` signatures stay stable across their consumers.
- Cross-system integration stays interface-only (public APIs, schemas, settings keys).

The full system/file map lives in `scope-assessment.agent.md` (for impact analysis) and `planning.agent.md` (for where to edit). The safe modify/freeze boundaries for a given change are set by `boundaries.agent.md` and validated by the user before planning.
