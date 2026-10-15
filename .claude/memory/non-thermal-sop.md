# Non-thermal C4H8 system: standard operating procedure

Written 2026-10-01. Companion document: `amech-dev/C4H8-prompt/FakeWell_in_automech.md`
(how AutoMech builds and post-processes the fake wells found in every abstraction input).

All paths are relative to `/data/home/csoulie/non_thermal/` (the same folder as `/home/csoulie/non_thermal/`)
unless they start with `/`.

---

## 1. What the system is

The system models **prompt (non-thermal) dissociation of butenyl radicals** formed by H-abstraction from butene.

```
           RADICAL GENERATION (12 abstraction channels)               RADICAL DECOMPOSITION (1 PES)
  C4H8-1 / C4H8-2  +  H, O, OH, CH3  ──►  C4H71-3* or C4H71-4*  +  H2 / OH / H2O / CH4
                                                │  hot radical, carrying part of the reaction exothermicity
                                                ▼
                       C4H7 PES:  C4H71-3 ⇌ C4H71-4
                                  C4H71-3 / C4H71-4 → C4H6 + H
                                  C4H71-4 → C2H4 + C2H3
                                  (or collisional stabilisation of C4H71-3 / C4H71-4)
```

- **Radical-generation inputs** compute the abstraction k(T,P) and the **product energy distribution (PED)**
  of the products (`ped.out`). They also print the fragments' **densities of states** (`ke.out`), which are
  used to split the energy between the radical and its partner.
- The **decomposition input** (C4H7 PES) computes, for each starting energy of the hot radical
  (`HotEnergies`), the fraction that stabilises, isomerises or dissociates (written to `mess.log`).
- `prompt.py` (mechanalyzer) convolves the two:
  - for each abstraction it gives the fraction of radicals that dissociate "promptly";
  - it rewrites the abstraction as e.g. `C4H8-1 + H => H2 + C4H6 + H`;
  - it fits everything to PLOG.

Species (`AUTOMECH_INPUT/species.csv`):

| name | SMILES | what it is |
|---|---|---|
| C4H8-1 | `CCC=C` | 1-butene |
| C4H8-2 | `CC=CC` | 2-butene |
| C4H71-3 | `C[CH]C=C` | 1-methylallyl (resonance-stabilised, allylic) |
| C4H71-4 | `[CH2]CC=C` | 3-buten-1-yl (primary, not resonance-stabilised) |

From 2-butene only C4H71-3 can be formed directly. C4H71-4 can appear in 2-butene results only through
**prompt isomerisation** of hot C4H71-3 on the C4H7 PES.

---

## 2. Where everything is

| path | content |
|---|---|
| `AUTOMECH_INPUT/` | **The definition of the system.** `mechanism.dat` (5 PESs, 17 reactions), `pes_groups.dat` (4 prompt groups), `run.dat` (which PES/channels were computed), `species.csv`, `models.dat`, `theory.dat`, `sorting/sort.dat` |
| `ME_INPUT/` | 11 MESS inputs (`*.inp`), one per abstraction channel. Inputs only, no outputs |
| `amech-dev/C4H8-prompt/` | **Run folders** (input + outputs) for 7 abstraction channels + 2-O + the C4H7 PES; `prompt.py`; `instructions.txt`; `rates_equip_simple.txt` (result for the H and OH groups); `test_change_prodEN/` (sensitivity tests on product energies) |
| `RATE CONSTANTS/` | Final results for the **full** system: `base.txt` (thermal rates, no prompt), `prompt_thermal.txt`, `prompt_rovib_dos.txt` (prompt rates with two energy-partition models) |
| `/data/home/csoulie/automech/` | AutoMech source (mechdriver, autoio/mess_io, autochem, mechanalyzer) with git history |

The `amech-dev/C4H8-prompt/*/mess.inp` files are **byte-identical** to the corresponding `ME_INPUT/*.inp`.

---

## 3. The 13 MESS inputs of the full system

PES numbers and channel numbers come from `AUTOMECH_INPUT/mechanism.dat`.
In that file each abstraction channel is its own sub-PES, which is why each one has its own MESS input
with its own zero of energy (the reactants are at 0 kcal/mol).

| PES:chn | reaction | MESS input | run folder with outputs | used by `prompt.py` `FLDs` |
|---|---|---|---|---|
| **1** (hot) | C4H7 PES (4 barriers, see §3.1) | `amech-dev/C4H8-prompt/C4H7_JC/wellcap_eigmax02/mess.inp` | ✅ | ✅ |
| 2:1 | C4H8-1 + H → C4H71-3 + H2 | `ME_INPUT/H_C4H71-3.inp` | ✅ `H_C4H71-3/` | ✅ |
| 2:2 | C4H8-1 + H → C4H71-4 + H2 | `ME_INPUT/H_C4H71-4.inp` | ✅ `H_C4H71-4/` | ✅ |
| 2:3 | C4H8-2 + H → C4H71-3 + H2 | `ME_INPUT/2-H_C4H71-3.inp` | ✅ `2-H_C4H71-3/` | ✅ |
| 3:1 | C4H8-1 + O → C4H71-3 + OH | `ME_INPUT/O_C4H71-3.inp` | ❌ not run | ❌ |
| 3:2 | C4H8-1 + O → C4H71-4 + OH | ❌ **missing everywhere** (would be `O_C4H71-4`) | ❌ | ❌ |
| 3:3 | C4H8-2 + O → C4H71-3 + OH | `ME_INPUT/2-O_C4H71-3.inp` | ✅ `2-O_C4H71-3/` | ❌ (run but not included) |
| 4:1 | C4H8-1 + OH → C4H71-3 + H2O | `ME_INPUT/OH_C4H71-3.inp` | ✅ `OH_C4H71-3/` | ✅ |
| 4:2 | C4H8-1 + OH → C4H71-4 + H2O | `ME_INPUT/OH_C4H71-4.inp` | ✅ `OH_C4H71-4/` | ✅ |
| 4:3 | C4H8-2 + OH → C4H71-3 + H2O | `ME_INPUT/2-OH_C4H71-3.inp` | ✅ `2-OH_C4H71-3/` | ✅ |
| 5:1 | C4H8-1 + CH3 → C4H71-3 + CH4 | `ME_INPUT/CH3_C4H71-3.inp` | ❌ not run | ❌ |
| 5:2 | C4H8-1 + CH3 → C4H71-4 + CH4 | `ME_INPUT/CH3_C4H71-4.inp` | ❌ not run | ❌ |
| 5:3 | C4H8-2 + CH3 → C4H71-3 + CH4 | `ME_INPUT/2-CH3_C4H71-3.inp` | ❌ not run | ❌ |

Summary:

- **8 of 13** have run folders with outputs.
- **4** exist only as inputs: `O_C4H71-3`, `CH3_C4H71-3`, `CH3_C4H71-4`, `2-CH3_C4H71-3`. All four already
  contain the prompt keywords (`PEDOutput`, `PEDSpecies`, `MicroRateOutput`, `density` fragments), so they
  are ready to run.
- **1** is missing: `O_C4H71-4`. Its rates are in `RATE CONSTANTS/*.txt`, so it existed at some point.
  It is not on this machine (searched `non_thermal`, `automech`, `GAME`, `projects`, `kmo_dev`, `tests_M1`, `tmp`, `MESS`).
  To regenerate it, rerun AutoMech for PES 3 channel 2. `run.dat` points to the AutoMech data store on
  LCRC (`/lcrc/project/PACC/AutoMech/data/run` and `.../save`).
- The current `prompt.py` `FLDs` list contains only **groups 1 (H) and 2 (OH)** plus the C4H7 PES.

### 3.1 The C4H7 PES (PES 1)

- `mechanism.dat` lists 5 channels for PES 1:

  | channel | reaction |
  |---|---|
  | 1.1.1 | C4H71-4 = C4H6 + H |
  | 1.1.2 | C4H71-4 = C2H4 + C2H3 |
  | 1.1.3 | C4H71-3 = C4H71-4 |
  | 1.1.4 | C4H71-3 = C4H6 + H |
  | 1.1.5 | C4H71-3 = C2H4 + C2H3 |

- `run.dat` computes only `1: 1-4`. Channel 5 is not a separate barrier: MESS produces it by going
  through C4H71-4.
- The input actually used is **`C4H7_JC/wellcap_eigmax02`**: a hand-built MESS input, not AutoMech-written.
  - Wells C4H71-3 (−45.63 kcal/mol) and C4H71-4 (−28.82); bimolecular C4H6+H (0) and C2H4+C2H3 (+4.65).
  - Barriers: B1 C4H6+H ↔ C4H71-3; B2 C4H6+H ↔ C4H71-4; B3 C4H71-3 ↔ C4H71-4; B4 C4H71-4 ↔ C2H4+C2H3.
  - `HotEnergies`: `C4H71-3 -45:1:250` and `C4H71-4 -28:1:230`, i.e. from the bottom of each well, in 1 kcal/mol steps.
  - Well extension: `WellExtension 0.001`, `ExtensionCorrection 0.4`, and
    `WellExtensionCap` 53 (C4H71-3) and 40 (C4H71-4) kcal/mol.
- Evidence that this is the input behind the final results: its rate constants reproduce the C4H7 rates in
  `RATE CONSTANTS/base.txt` to within a factor of about 1.15 (at worst 0.86–1.26) over 1000–2000 K and 0.1–10 atm.
  The other variant, `C4H7_JC/nowellext` (in `test_change_prodEN/`), matches worse and has no values at high T.

### 3.2 Prompt groups (`AUTOMECH_INPUT/pes_groups.dat`)

| group | idxs (PES:subPES) | PED reactions | hot species |
|---|---|---|---|
| 1 (H) | 2:1, 2:2, 2:3, 1:1 | C4H8-1+H=C4H71-3+H2, C4H8-1+H=C4H71-4+H2, C4H8-2+H=C4H71-3+H2 | C4H71-3, C4H71-4 on 1:1 |
| 2 (OH) | 4:1, 4:2, 4:3, 1:1 | same pattern with OH → H2O | same |
| 3 (CH3) | 5:1, 5:2, 5:3, 1:1 | same pattern with CH3 → CH4 | same |
| 4 (O) | 3:1, 3:2, 3:3, 1:1 | same pattern with O → OH | same |

The group settings are `modeltype = thermal` and `bf_threshold = 0.1`.

---

## 4. Naming conventions

- **Folder or input name** `[2-]<abstractor>_<radical>`:
  - no prefix → 1-butene (C4H8-1);
  - `2-` prefix → 2-butene (C4H8-2).
  - Example: `2-OH_C4H71-3` = C4H8-2 + OH → C4H71-3 + H2O.
- **PES numbers** (assigned by mechanalyzer by sorting on 1000·C + 100·O + H):

  | PES | formula | sort key |
  |---|---|---|
  | 1 | C4H7 | 4007 |
  | 2 | C4H9 | 4009 |
  | 3 | C4H8O | 4108 |
  | 4 | C4H9O | 4109 |
  | 5 | C5H11 | 5011 |

- **TS label in MESS**: `ts_<PES>_<channel>`. For example `ts_4_3` is PES 4, channel 3.
- **Fake wells and fake barriers** (see `FakeWell_in_automech.md`). Two AutoMech eras are mixed in these inputs:

  | inputs | well label | barrier labels | era |
  |---|---|---|---|
  | `H_C4H71-3`, `H_C4H71-4`, `OH_C4H71-3`, `OH_C4H71-4`, `CH3_C4H71-3`, `CH3_C4H71-4`, `2-CH3_C4H71-3` | `FW-<A+B>` | `FRB<n>` / `FPB<n>` | Mar–Apr 2022 |
  | `2-H_C4H71-3`, `2-OH_C4H71-3`, `2-O_C4H71-3`, `O_C4H71-3` | `FakeW-<A+B>` | `FakeRB<n>` / `FakePB<n>` | Apr–Nov 2022 |

  All of them: fake-well depth 1 kcal/mol, PST fake barrier at the asymptote energy.

---

## 5. What each MESS input must contain

These are set automatically by AutoMech when `pes_groups.dat` is used. Check them when editing by hand
(details in `amech-dev/C4H8-prompt/instructions.txt`).

**Abstraction (PED) input**, in the global section:

```
PEDOutput        ped.out
PEDSpecies       C4H8-1+H=C4H71-3+H2      ! names exactly as in this input
MicroRateOutput  ke.out
MicroEnerMin[kcal/mol]   0.1
MicroEnerMax[kcal/mol]   320.0
MicroEnerStep[kcal/mol]  0.1
```

In the product `Bimolecular` block, both fragments need the `density` keyword:

```
Fragment C4H71-3 density
Fragment H2 density
```

**C4H7 (hot) input**, in the global section:

```
HotEnergies[kcal/mol]  2
C4H71-3 -45:1:250
C4H71-4 -28:1:230
WellExtension          0.001       ! recommended
ExtensionCorrection    0.4
```

Each well should also have `WellExtensionCap[kcal/mol]`.

**How `prompt.py` links them.** A folder is classified as PED if its input has `PEDSpecies`, as hot if it has
`HotEnergies`, or as both. A PED folder is chained to a hot folder when a PED product fragment name equals a
`HotEnergies` species name, so **species names must match exactly** across inputs (`C4H71-3`, `C4H71-4`).

---

## 6. Procedure

### 6.1 Environment

```bash
source ~/.bashrc
conda activate automech        # /home/csoulie/.conda/envs/automech
```

This environment provides the `mess` and `mess_mpi` binaries and the Python packages `prompt.py` needs:
`mechanalyzer`, `mess_io`, `ratefit`, `chemkin_io`, `ioformat`, `autoparse`. The packages are installed from
the local checkout in `/data/home/csoulie/automech/`.

The `kimeco` environment has `mess_io` but **not** `mechanalyzer`, so it cannot run `prompt.py`.

### 6.2 Make a run folder for an input

```bash
cd /data/home/csoulie/non_thermal/amech-dev/C4H8-prompt
mkdir CH3_C4H71-3
cp ../../ME_INPUT/CH3_C4H71-3.inp CH3_C4H71-3/mess.inp    # prompt.py expects the name mess.inp
```

### 6.3 Run MESS

Locally (equivalent to the existing `run.sh` files, which use `mess mess.inp >> stdout.log &> stderr.log`):

```bash
cd CH3_C4H71-3
export OMP_NUM_THREADS=8
mess mess.inp > stdout.log 2> stderr.log
```

Or with Slurm (pattern from `non_thermal/mess_roo.slurm`):

```bash
#!/bin/bash
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH -p week-long-cpu
#SBATCH -q medium
#SBATCH -o mess.stdout
#SBATCH -e mess.err
export OMP_NUM_THREADS=1
source ~/.bashrc
conda activate automech
mess mess.inp
```

### 6.4 Check the run

- The last lines of `mess.log` contain `MasterEquation::direct_diagonalization_method: done`.
- The folder contains `rate.out` and `mess.log`.
  - PED folders also need `ped.out` and `ke.out`.
  - The hot folder needs `mess.inp`, `rate.out` and `mess.log`; `ke.out` is optional there.
- `ped.out` can be large: about 1.5 MB here, but several GB for bigger systems (`ooqooh_ped.out` is 5 GB).

### 6.5 Run `prompt.py`

`prompt.py` is in `amech-dev/C4H8-prompt/`. The only line to edit is `FLDs`: the list of run folders, relative to
the current directory. Include every PED folder of interest **plus** the hot folder.

Current list (groups H and OH):

```python
FLDs = ['H_C4H71-3','H_C4H71-4','OH_C4H71-3','OH_C4H71-4','2-H_C4H71-3','2-OH_C4H71-3','C4H7_JC/wellcap_eigmax02']
```

Full system (once the missing runs exist):

```python
FLDs = ['H_C4H71-3','H_C4H71-4','2-H_C4H71-3',
        'O_C4H71-3','O_C4H71-4','2-O_C4H71-3',
        'OH_C4H71-3','OH_C4H71-4','2-OH_C4H71-3',
        'CH3_C4H71-3','CH3_C4H71-4','2-CH3_C4H71-3',
        'C4H7_JC/wellcap_eigmax02']
```

Run it:

```bash
cd /data/home/csoulie/non_thermal/amech-dev/C4H8-prompt
conda activate automech
python prompt.py -m rovib_dos -b 0.01      # see options below
```

| option | default | meaning |
|---|---|---|
| `-m` | `equip_simple` | energy-partition model. **Recommended: `rovib_dos`** (uses `ke.out`). Others: `equip_phi`, `beta_phi1a`, `beta_phi2a`, `beta_phi3a`, `thermal` |
| `-b` | `0.01` | minimum branching fraction to keep a prompt channel. `pes_groups.dat` used 0.1 |
| `-f` | `plog` | fit form |
| `-o`, `-omicro`, `-l` | `rate.out`, `ke.out`, `mess.log` | output file names |

Outputs, written to the current directory:

- `rates_<model>.txt`: CHEMKIN-format PLOG rates (thermal + prompt);
- `bf_<model>_<PED reaction>_<product>.txt`: prompt branching fractions vs T and P.

**Verified 2026-10-01** on a scratch copy, with the current `FLDs` and default options in the `automech` env:

- the run takes about 7 minutes;
- the 20 real reactions of the existing `rates_equip_simple.txt` are reproduced to within 0.7 %;
- `RuntimeWarning: overflow …` messages from the Arrhenius fit are printed and are harmless here;
- **but** the new file also contains 10 spurious `FW-` reactions (see §8, point 1). Delete them.

### 6.6 Compare with the reference results

`RATE CONSTANTS/` contains:

- `base.txt`: no prompt;
- `prompt_thermal.txt`, `prompt_rovib_dos.txt`: the full system.

A new full-system run with `-m rovib_dos` should be compared with `prompt_rovib_dos.txt`.

---

## 7. Status and to-do

1. Run the four ready inputs: `O_C4H71-3`, `CH3_C4H71-3`, `CH3_C4H71-4`, `2-CH3_C4H71-3` (§6.2–6.4).
   For the three CH3 inputs, first rename `FW-` → `FakeW-` (§8, point 1).
2. Regenerate `O_C4H71-4` (PES 3, channel 2) with AutoMech. It needs the AutoMech save filesystem on LCRC.
3. Decide whether `2-O_C4H71-3` should be in `FLDs`. It has been run and is complete, but it is not used.
   It makes sense to include it only together with `O_C4H71-3` and `O_C4H71-4`, i.e. the whole O group.
4. Clean the `FW-` artefacts from any rate file produced from the old-era run folders (§8, point 1).

---

## 8. Pitfalls

1. **Old `FW-` fake-well labels are not recognised by the current `mess_io`.** Its filter looks for `Fake`.
   With the current code, `prompt.py` therefore writes **10 spurious reactions** into `rates_<model>.txt`
   for the current `FLDs` (verified). Examples: `C4H8-1 + H = FW-C4H8-1 + H`,
   `FW-C4H8-1 + OH = FW-C4H71-3 + H2O`. They are fitted from high-pressure values of fake-well steps
   and have no physical meaning.
   - Already-run folders (`H_*`, `OH_*` without the `2-` prefix): delete every reaction containing `FW-`
     from the output rate file.
   - Inputs not yet run (`CH3_C4H71-3`, `CH3_C4H71-4`, `2-CH3_C4H71-3`): rename the labels before running MESS:
     `sed -i 's/FW-/FakeW-/g' mess.inp`.
     The reader parses the labels printed in `rate.out`, so renaming only after the run has no effect.
2. **The PED energy zero is the product `GroundEnergy`, not the fake well.** If you change a product
   energy, move the product fake well and the fake barrier with it, and update the second Eckart
   `WellDepth` of the inner TS. Otherwise you create an artificial exit barrier. See the `test_change_prodEN/`
   folder and `FakeWell_in_automech.md` §4.
3. **Collision models differ.**
   - All abstraction inputs use the same AutoMech estimate: C4H8 in Ar, mass 56.063/39.962 amu,
     ε 173.667 cm⁻¹, ΔE_down 609.97·(T/300)^0.521 cm⁻¹.
   - `C4H7_JC` uses N2 (mass 28), ε 93.9/68 cm⁻¹, ΔE_down 100·(T/300)^0.8 cm⁻¹ (comment: "1MA from AWJ").
   - Collisions matter only on the C4H7 PES, so this is mostly harmless, but the bath gases are not consistent.
4. **Same T/P grid everywhere.** 23 temperatures from 500 to 2500 K, and pressures 0.03, 0.1, 0.3, 1, 3, 10,
   30, 100 atm. Keep this grid in any new input so `prompt.py` can combine them.
5. **Different defaults in different places.**
   - `prompt.py`: `equip_simple` model, threshold 0.01.
   - `pes_groups.dat`: `thermal` model, threshold 0.1.
   - Final results: `thermal` and `rovib_dos`.
   - Always state which model and threshold were used.
6. **`instructions.txt`, "tests" section, has two inaccuracies.**
   - `loweren` lowers the products by 4 kcal/mol, not 2.
   - The smaller prompt effect in `loweren_fakew_andprds` comes from its smaller shift (2 vs 4 kcal/mol),
     not from the extra low-energy points in the PED.

---

## 9. How this was established

- System definition: `AUTOMECH_INPUT/mechanism.dat`, `pes_groups.dat`, `run.dat`.
- Before those files were found, the PES and channel numbers had already been predicted from the TS labels
  and mechanalyzer's PES-sorting rule (`mechanalyzer/builder/sort_fct.py` + `parser/_util.count_atoms`).
- Identity of run folders: byte-wise comparison with `ME_INPUT/*.inp`.
- Completeness of the final results: all 12 abstraction reactions (including `C4H8-1 + O = C4H71-4 + OH`) and
  the C4H7 reactions appear in `RATE CONSTANTS/*.txt`.
- C4H7 input identification: rate comparison of `C4H7_JC/wellcap_eigmax02/rate.out` vs `RATE CONSTANTS/base.txt` (§3.1).
- Run completeness: last lines of each `mess.log`. T/P grids: compared across all 8 run folders.
