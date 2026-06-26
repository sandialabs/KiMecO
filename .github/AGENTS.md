# Multi-Agent Architecture For GAME

## Hierarchy

Root Coordinator Agent
- Runtime Lead Agent
  - Run Orchestration Agent
  - Execution Pipeline Agent
  - Optimization Agent
  - Scheduler and Simulation Agent
- Experience and Data Lead Agent
  - Input and Config Agent
  - Mechanism and SOP Agent
  - Persistence, UI, and Postprocess Agent

## Domain Ownership Map

| Agent | Owned paths |
| --- | --- |
| Run Orchestration | `kimeco/__init__.py`, `kimeco/main.py`, `kimeco/_kimeco.py`, packaging/CI (`pyproject.toml` scripts, `kmo_install_test.sh`, `.gitlab-ci.yml`) |
| Execution Pipeline | `kimeco/core.py`, `kimeco/generation.py`, `kimeco/model.py`, `kimeco/goat.py`, `kimeco/scoring_f/`, `kimeco/sensitivity/` |
| Optimization | `kimeco/optimizers/`, `kimeco/Perturbators/` |
| Scheduler and Simulation | `kimeco/q_sys.py`, `kimeco/rate_coef.py`, `kimeco/simulation.py`, `kimeco/experiments/`, `kimeco/templates/` (job/array), `kimeco/cantera/` |
| Input and Config | `kimeco/user_input.py`, `kimeco/default_settings.py`, `kimeco/enums.py`, `kimeco/logger_config.py` |
| Mechanism and SOP | `kimeco/parameters.py`, `kimeco/barrier.py`, `kimeco/well.py`, `kimeco/bimolecular.py`, `kimeco/kinmec.py`, `kimeco/rotors/`, `kimeco/readers/`, `kimeco/writers/`, `kimeco/templates/ct_reaction_tpl.py` |
| Persistence, UI, and Postprocess | `kimeco/database/`, `kimeco/gui/`, `kimeco/postprocessing/` |

Every `kimeco/` module has exactly one owner; `tests/` is shared and edited by the agent that owns the code under test.

## Ownership Model

- Agents edit only files inside their declared scope.
- Cross-domain modifications require routing through Root Coordinator Agent.
- Leads arbitrate boundary questions before specialist edits begin.

## Interaction Rules

- Use interfaces, not internals: agents consume public methods and stable data contracts.
- No direct cross-domain edits without coordinator approval.
- For multi-domain work, Root Coordinator Agent requests plans/sign-off from both affected leads, then dispatches the owning specialist(s) to execute, and obtains final consistency approval from the leads.
- Subagent invocations are flat: the coordinator dispatches leads for review/sign-off and specialists for edits; nested delegation is not assumed.
- If contract risk exists (schema, input format, status transitions), both relevant leads must approve.

## Consistency Gates

- Input and Config Agent protects input schema and enum semantics.
- Persistence, UI, and Postprocess Agent protects DB schema compatibility and UI callback contracts.
- Execution Pipeline Agent protects model and job lifecycle state transitions.
- Runtime Lead Agent validates algorithm and runtime coherence before completion.

## Shared Invariants

- ModelStatus and JobStatus transitions remain valid and monotonic where expected.
- SOP, KIN, and SIM DB table contracts stay compatible unless an explicit migration task is requested.
- GOAT generation indexing and file semantics remain stable.
- The `GOATs.from_file` / `Scoring` (scoring_f) contract is owned by Execution Pipeline Agent; changes require Runtime Lead sign-off and lockstep updates to GUI consumers (persistence-ui-postprocess).
