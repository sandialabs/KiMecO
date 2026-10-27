---
name: relabel-mess-by-structure
description: "Names a molecule from its 3D geometry as a connectivity-only condensed formula (e.g. CH2CHCH2CH3) and rewrites a folder of AutoMech MESS inputs with structure-based labels, so the same species, fake well or barrier carries the same label in every file. Ships relabel_mess.py: 'formula' (xyz in angstrom -> name) and 'relabel' (folder -> renamed copies, <stem>.map.json old->new maps, rename_report.md). Use when several separately written MESS inputs must be merged into one SOP, when labels such as FRB1/FPB1, FW-/FakeW- or C4H8-1 mean different things in different files, when a species name must come from an .xyz file or a MESS Geometry block, or when relabel prints 'STOP smiles', 'STOP collision', 'STOP real-well' or 'unsupported'."
---
# Relabel MESS inputs by structure

## When to use

- Several AutoMech MESS inputs (fake wells, bimoleculars, phase-space-theory barriers, saddle points), written separately, must be read together (e.g. one KiMecO SOP) and their labels clash or alias each other.
- A species name is needed from an `.xyz` file or from the first `Geometry[angstrom]` block of a MESS species.
- Not for: rings (unsupported), real (non-fake) wells, hot PESs, inputs without AutoMech SMILES comments. Those stop the run; extending the script is pipeline work.

## Prerequisites

- Conda env `kimeco` (numpy, ase, rdkit): `source ~/miniconda3/etc/profile.d/conda.sh && conda activate kimeco`.
- Inputs: one folder of `*.inp` files with AutoMech SMILES comments on every `Fragment` (`! <smiles>`) and `Bimolecular` (`! [<smiA> + <smiB>]`) line; geometries in angstrom.
- An output folder outside the repository and different from the input folder (originals are read only).

## Steps

1. Name single structures (optional):
   `python .claude/skills/relabel-mess-by-structure/relabel_mess.py formula a.xyz b.xyz`
   prints `<path>: <name>`; several molecules in one file print `A+B`; a structure it cannot name prints `<path>: unsupported (<reason>)` and exit code 3.
2. Relabel a folder:
   `python .claude/skills/relabel-mess-by-structure/relabel_mess.py relabel IN_DIR OUT_DIR [--force]`
   (`--force` only to overwrite a non-empty `OUT_DIR`). Run it from a scratch directory, not from the input folder.
3. Read `OUT_DIR/rename_report.md`: species names and SMILES cross-check, composite labels with lengths, aliases merged, old labels reused for different items, collisions, heavy-atom RMSD, bond-threshold margins, KIN_DB name length, mess_io note, built-in checks.
4. Before using the renamed set, run MESS on the original and the renamed copy of the files with the longest labels, with the same `mess` binary and thread setting, in a scratch directory (MESS writes `rate.out`, `ped.out`, `ke.out`, `<stem>.log`, `<stem>.aux` into its working directory). Compare `rate.out`/`ped.out` values by (T, P, from, to) after mapping the new labels back through `<stem>.map.json`; they must be identical. Append the result to the report as `## MESS check`.
5. Hand the maps to whatever consumes the names next (mechanism species names, SOP items, `input.json`).

## Naming rule (as implemented)

- Bond when `d_ij <= BOND_SCALE * (r_i + r_j)`, `BOND_SCALE = 1.2`, radii `ase.data.covalent_radii`.
- Each heavy atom = symbol + H count (`C`, `CH`, `CH2`, `CH3`); no bond orders, radical or cis/trans markers; heavy skeleton must be a tree; main chain = a longest path, branches in `()`, smallest ASCII string wins (`CH2CHCH2CH3`, `CH3CH(CH3)CH3`).
- ≤ 1 heavy atom: usual formula (`H`, `H2`, `O`, `OH`, `H2O`, `CH3`, `CH4`); `Atom` fragments: element from `Mass[amu]` (±0.1 amu).
- Composites: bimolecular `<A>+<B>` (Fragment block order); fake well `FakeW-<bimolecular label>` (old `FW-`/`FakeW-` both accepted); barrier `<lside>=<rside>` (Barrier line order, saddle points included).

## Key files

- `.claude/skills/relabel-mess-by-structure/relabel_mess.py` — `MolecularGraph`, `_SkeletonWriter` (naming), `MessInputFile` (parsing and token-span rewrite), `Relabeler` (phases and checks), `RelabelOutputWriter` (outputs), constants at the top (`BOND_SCALE`, `FORBIDDEN_LABEL_PARTS`, `KIN_DB_NAME_LIMIT`, exit codes).
- `kimeco/readers/mess_input.py` — KiMecO label rules (`.`/`__` rejected, "geom" in fragment labels misread).
- `kimeco/database/kin_db.py` — `batch_select` reads well/bimolecular names back as 30-character strings (hence the `kin-db` warning).

## Checks & pitfalls

- Exit codes: 0 ok; 1 blocking check failed (`STOP <kind> <file>:<line>: …` on stderr, **nothing written**); 2 usage or input-format error (incl. `OUT_DIR` = `IN_DIR`, non-empty `OUT_DIR` without `--force`); 3 `formula` met an unsupported structure.
- STOP kinds: `smiles`, `missing-smiles`, `unsupported`, `atom`, `fake-well`, `real-well`, `pst`, `ts-formula`, `units`, `format`, `label-rule`, `collision`, `reversed-barrier`, `resolution`, `coverage`, `flat-map`, `round-trip`. WARNING kinds (non-blocking, also in the report): `bond-margin`, `rmsd`, `kin-db`, `no-geometry`.
- Never loosen `BOND_SCALE` to silence a stop: H2 in AutoMech inputs sits about 0.004 Å inside the 1.2 limit (reported as `bond-margin`); a split H2 is caught by the SMILES check.
- Species labels never contain `=`: mess_io splits `PEDSpecies` on `=`. Barrier labels contain exactly one `=` (MESS accepts it).
- Fake wells must stay `FakeW-<exact bimolecular label>` and bimoleculars `<frag>+<frag>`: mess_io identifies fake wells and bimolecular products from these forms.
- Any label containing an uppercase `F` (all `FakeW-…=…` barrier names) is treated as fake by mess_io `_pes.pes(read_fake=False)`; stated in the report.
- Never add `UseShortNames` to inputs KiMecO reads: MESS then prints `W1`/`P1` labels and KiMecO stores k = 0 silently.
- MESS limits no label length (unbounded `std::string`; 43-character labels run with identical rates). Long labels only run together in some fixed-width headers (log partition-function tables, `ke.out` per-well headers); `rate.out`, `ped.out` and the `ke.out` bimolecular density-of-states header that mess_io's prompt workflow parses widen to fit.
- `conda run -n kimeco …` prints an extra `ERROR conda.cli.main_run` line on a non-zero exit; harmless.

## Lane

- Running the skill (`formula`, `relabel` with outputs outside the repo, MESS checks in a scratch directory) is **operational**: no repository path is created or modified.
- Editing `relabel_mess.py` or this file is a repository change: **pipeline** lane.
