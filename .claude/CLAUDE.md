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

## Project memory

@memory/sop-parameters-from-mess-input.md

### Non-thermal / prompt kinetics (C4H8 system): read on demand

These notes are NOT loaded automatically. Read the relevant file with the Read tool only when the
task touches its topic (prompt / non-Boltzmann kinetics, the C4H8 system, AutoMech fake wells,
MESS `ped.out`, PESViewer). Paths are relative to the repository root. `[[name]]` links inside the
notes refer to the `name:` field of another note in this list.

- `.claude/memory/c4h8-prompt-system-map.md` (`c4h8-prompt-system-map`): the 13 MESS inputs
  (5 PESs) of the C4H8 prompt system, where each lives, which one is missing. Start here.
- `.claude/memory/prompt_branching_fractions.md` (`prompt-branching-fractions`): how prompt
  branching fractions and k = BF·k1 are computed (data per PES, models, Eq. 9), with a code map.
- `.claude/memory/ped_output_file.md` (`ped-output-file`): MESS `PEDOutput` (`ped.out`) block
  layout, energy zero, typical α(E), P-independence, how `mess_io` `get_ped` reads it.
- `.claude/memory/prompt-paper-reference.md` (`prompt-paper-reference`): the source paper
  (Pratali Maffei et al., CNF 2023) and where to read its full text.
- `.claude/memory/automech-fake-wells-doc.md` (`automech-fake-wells-doc`): where the fake-well
  write-up, the AutoMech source checkout and the `automech` conda env live.
- `.claude/memory/pesviewer-c4h8-inputs.md` (`pesviewer-c4h8-inputs`): the `PESVIEWER` input
  layout and PESViewer bugs (single-TS crash, ignored `save` argument, TkAgg).
- `.claude/memory/non-thermal-sop.md`: full standard operating procedure for the non-thermal C4H8
  system (system map, run procedure, pitfalls). Long; read the sections you need.
- `.claude/memory/FakeWell_in_automech.md`: detailed write-up of how AutoMech builds, reads and
  post-processes MESS fake wells, with version history. Long; read the sections you need.
