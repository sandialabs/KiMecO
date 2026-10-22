## Available CLI tools

Prefer the use of the following CLI tools if they are available on PATH:

- `fzf` — interactive fuzzy finder
- `rg` — fast file/content search
- `bat` — enhanced `cat` with syntax highlighting
- `gh` — GitHub CLI
- `jq` — JSON processing
- `zoxide` — smarter directory navigation
- `eza` — enhanced `ls`

Prefer these tools when appropriate. In particular:
- Use `rg` instead of `grep` for searching files.
- Use `eza` instead of `ls` when useful.
- Use `bat` instead of `cat` when displaying source/code files.
- Use `jq` for JSON manipulation.
- Use `fzf` for interactive selection when useful.

## Pipeline agents: step files and memory candidates

These apply to every stage agent dispatched by the workflow orchestrator.

- **Step files.** When the orchestrator gives you `.claude/work/<topic>/chain.md` and `step.md`, read
  both first. `chain.md` holds the verbatim request, the validated step chain and the handoffs of
  the finished steps. `step.md` holds the current step: its goal, specification, the user's
  decisions, the validated boundaries, the confirmed plan and test design. Only the orchestrator
  edits these files.
- **Current step only.** Never plan, implement, test or document anything that belongs to a later
  step. Something that belongs to a later step is not a gap of this step: mention it in one line.
- **Earlier steps.** Their handoffs say what they changed and which decisions later steps must
  respect. Verify in the code before relying on them.
- **Memory candidates.** End your report with the facts you verified during this work that a later
  task would need and could not quickly re-derive from the code: a non-obvious invariant, a
  pitfall, an external tool's behaviour, where something lives. Give each its source
  (`file:symbol`, a command and its output, or a URL) and mark it `portable` or
  `machine-specific`; mark facts about this step's own changes `uncommitted`. Write "none" when
  there are none; never pad.

## Project memory

Memory notes hold verified, reusable facts that are slow to re-derive from the code. None is loaded
automatically: read a note with the Read tool only when the task touches its topic. Paths are
relative to the repository root. `[[name]]` links inside a note refer to the `name:` field of
another note, tracked or local.

Rules for every agent:
- Before you finish a task, check whether it explored or created complicated logic that a future
  session would otherwise have to work out again: how an algorithm or data flow works across
  several files, a non-obvious invariant, an external tool's behaviour, a pitfall that cost time.
  If so, write or extend a note with the `record-memory-note` skill before you report; skip routine
  work. Pipeline subagents report it as a memory candidate instead.
- A note describes code that exists in the repository alongside it, or external facts. Never write
  a note about planned, in-progress or discarded work: step chains, step specs, drafts and review
  notes live in `.claude/work/` (gitignored). Note edits are part of a step's diff, committed or
  discarded together with its code.
- Tracked notes (`.claude/memory/`) are portable: no machine-specific paths, envs or hosts. Those go
  in `.claude/memory-local/`, indexed in `CLAUDE.local.md` at the repository root. Both are
  gitignored and may be absent on another machine.
- When the code or the facts a note describes change, update or delete the note in the same step.
  Keep only what a later task will need.

### Non-thermal / prompt kinetics (C4H8 system): read on demand

For prompt / non-Boltzmann kinetics, AutoMech fake wells and MESS `ped.out`. The system map, run
procedure, file locations and PESViewer notes are local (see `CLAUDE.local.md`).

- `.claude/memory/prompt_branching_fractions.md` (`prompt-branching-fractions`): how prompt
  branching fractions and k = BF·k1 are computed (data per PES, models, Eq. 9), with a code map.
- `.claude/memory/ped_output_file.md` (`ped-output-file`): MESS `PEDOutput` (`ped.out`) block
  layout, energy zero, typical α(E), P-independence, how `mess_io` `get_ped` reads it.
- `.claude/memory/prompt-paper-reference.md` (`prompt-paper-reference`): the source paper
  (Pratali Maffei et al., CNF 2023) and where to read its full text.
- `.claude/memory/FakeWell_in_automech.md`: detailed write-up of how AutoMech builds, reads and
  post-processes MESS fake wells, with version history. Long; read the sections you need.
