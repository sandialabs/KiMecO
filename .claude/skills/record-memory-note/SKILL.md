---
name: record-memory-note
description: "Turn verified facts into KiMecO memory notes that later sessions and every agent can read: filter the candidates, re-verify them, choose a tracked (portable) or local (machine-specific) note, write or extend the note, and keep the indexes in .claude/CLAUDE.md and CLAUDE.local.md in sync. Use at the end of any task or session that explored or created complicated logic a future session would otherwise have to work out again (how an algorithm or data flow works across several files, a non-obvious invariant, a pitfall that cost time), when a pipeline step closes with memory candidates in .claude/work/<topic>/chain.md, when the user says remember, note, save or record this for later, or after an investigation uncovered a non-obvious fact (an external tool's behaviour, a pitfall, where data or code lives)."
---
# Record a memory note

## When to use

- A task or session is ending and it explored or created complicated logic that a future session
  would otherwise have to work out again: how an algorithm or data flow works across several
  files, a non-obvious invariant, a pitfall that cost time.
- A pipeline step closes (or its chain finishes): process the memory candidates collected in its
  `chain.md`.
- The user asks to remember, note, save or record something for later sessions.
- An investigation (operational lane, debugging, reading external code) established a fact that a
  later task will need and that took real effort to find.

Not for: plans, step specs or anything still to be done (that lives in `.claude/work/`); facts one
`rg` or one file read away; the user's personal working preferences (those go in
`~/.claude/CLAUDE.md`, and only after asking, because that file applies to every project).

## Prerequisites

- The memory rules in `.claude/CLAUDE.md` ("Project memory").
- The current indexes: `.claude/CLAUDE.md` (tracked notes) and `CLAUDE.local.md` (local notes).

## Steps

1. **Gather** the candidates: the "Memory candidates" list in `chain.md`, or the facts the user
   named. Each needs a source: `path::symbol`, a command and its output, or a URL.
2. **Filter.** Keep a candidate only if all of these hold, and note the reason for each one dropped:
   - **Verified now.** Re-read the cited `path::symbol`, re-run the command, or re-open the URL. A
     candidate marked `uncommitted` must match the working tree. Drop what no longer holds.
   - **Reusable.** A later task would need it.
   - **Not cheap to re-derive.** Not one search or one file read away; never a paraphrase of the code.
   - **Not already written down.** Search first, and prefer extending an existing note or linking
     a wiki/MANUAL page:
     ```bash
     rg -n -i "<keyword>" .claude/memory .claude/memory-local .claude/CLAUDE.md CLAUDE.local.md wiki MANUAL.md
     ```
   - **Not about planned, in-progress or discarded work.**
3. **Choose the destination.**
   - Portable (true on any machine) → `.claude/memory/<name>.md`, indexed in `.claude/CLAUDE.md`.
   - Machine-specific (absolute paths, hosts, conda envs, local data or checkouts) →
     `.claude/memory-local/<name>.md`, indexed in `CLAUDE.local.md`.
   - Both → split it: the portable fact in the tracked note, the locations in the local note.
   - A copy of an external document is never a note: point to the original instead (a copied
     document drifts, as `FakeWell_in_automech.md` did).
4. **Write or extend the note** (at most about 60 lines; longer material belongs in the wiki):
   ```markdown
   ---
   name: <kebab-case-name>          # equals the file name without .md
   description: "<one line: what the note tells and when it is useful>"
   type: project | reference        # project = about this codebase or its runs; reference = where to find external information
   verified: <YYYY-MM-DD> against <commit sha, or "working tree">
   ---
   <the fact or facts, short and specific>

   **Why:** <why it matters, or what goes wrong without it>
   **How to apply:** <when to use it>

   Sources: `path::symbol`, commands, URLs. Links to other notes: [[name]].
   ```
5. **Update the index**: one entry per note under a topic heading, in the same style as the
   existing entries: path, `name` in backticks, a one-line description. Keep `.claude/CLAUDE.md`
   under 200 lines.
6. **Verify**: re-read each note and index entry, then check the frontmatter and that tracked notes
   carry no machine-specific paths:
   ```bash
   python -c "import yaml,sys; t=open(sys.argv[1]).read().split('---')[1]; print(yaml.safe_load(t)['name'])" <note>
   rg -n "/data/home/|/home/[a-z]+/|~/\.conda/envs/" .claude/memory .claude/CLAUDE.md
   ```
7. **Clean up and report.** Remove the processed candidates from `chain.md`. Report each note
   created, extended or dropped (with the reason), in one line each.

## Key files

- `.claude/CLAUDE.md`: memory rules, the "Pipeline agents" memory-candidates format, the tracked index.
- `CLAUDE.local.md`: the local index (gitignored).
- `.claude/memory/`, `.claude/memory-local/` (gitignored): the notes.
- `.claude/work/<topic>/chain.md`: the memory candidates of a chain.
- `.gitignore`: ignores `CLAUDE.local.md`, `.claude/memory-local/`, `.claude/work/`.

## Checks & pitfalls

- Never store secrets, credentials or tokens.
- A note explains what is not obvious (why, where, pitfalls); it never restates the code. A long
  note describing code is how the removed SOP note (249 lines, describing discarded code) went wrong.
- Notes about a step's uncommitted changes are part of that step's diff: if the user discards the
  step, its notes go too.
- Claude Code's own auto memory (`~/.claude/projects/<project>/memory/`) is separate and does not
  reach subagents: never write project knowledge there.
- When a note's code changes later, `version-control` updates or deletes it in Stage 7.

## Lane

Writing notes is a bounded exception the orchestrator performs directly, like writing an approved
skill. Tracked notes appear in the git diff, for the user to review and commit. Local notes are
gitignored and never committed.
