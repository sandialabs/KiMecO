# Fake wells in AutoMech: how they are built, read and post-processed

Written 2026-10-01 from the source code and git history of a local AutoMech checkout and from the
MESS runs of the C4H8 prompt system (`C4H8-prompt/`). "This folder" below means that run folder. The
checkout, the run folder and the conda env are machine-specific; their locations are in the local
notes (`CLAUDE.local.md`), which may be absent on other machines.

Code versions inspected (clean checkouts, no local changes):

| repo | version | commit |
|---|---|---|
| mechdriver | Release 0.2026.1 | `e3b666a8` (2026-04-09) |
| autoio (`mess_io`) | Release 0.2026.0 | `3ebe2ff` (2026-03-06) |
| autochem (`automol`) | Release 0.2026.3 | `2677b1e8` (2026-04-07) |
| mechanalyzer (+ `ratefit`) | Release 0.2026.1 | `16f56f3` (2026-04-07) |

All `file:line` references below are relative to the repo's root and point to these versions.
Statements marked **(verified)** were checked by running code or by reading MESS outputs in this folder.
Statements marked **(code reading)** come from reading the source only.

---

## 0. Summary

- A **fake well** is an artificial van der Waals-like complex that AutoMech inserts between a
  bimolecular reactant (or product) pair and the tight transition state of a channel:
  `A+B ─FakeB─ FakeW-A+B ─TS─ FakeW-C+D ─FakeB─ C+D`.
- It is **not** a computed vdW complex: the geometry is the two fragments stacked about 3 Å apart.
  The energy is a fixed offset below the asymptote (3 kcal/mol now, 1 kcal/mol before Nov 2022).
  The intermolecular modes are dummy frequencies. The connection to the fragments is a generic
  phase-space-theory (PST) barrier placed at the asymptote energy.
- What it does in practice:
  - it gives the tight TS a well on each side, and the Eckart well depths are measured from those wells;
  - it makes a bimolecular-to-bimolecular channel look like an ordinary well-to-well isomerisation
    inside the master equation.
- **Detection is purely by name.** Post-processing finds fake wells because their label contains
  `Fake` (or `FakeW`), never by topology or energy.
- **Rate coefficients (current reader):**
  - reactions *from* a fake well are discarded;
  - reactions *to* a fake well have the `FakeW-` prefix stripped and their k(T,P) is added to the real
    reaction; the real reaction's high-pressure limit is kept and the fake one's is discarded;
  - hot-energy branching fractions of `FakeW-X` are added to `X`;
  - PEDs involving a fake well are skipped;
  - fake wells get no `WellExtensionCap`.
- **Older inputs** with `FW-` labels (from Mar–Apr 2022 code) are **not** recognised by the current
  reader's `Fake` test, so their reactions leak through **(verified)**.
- For prompt dissociation, the fake wells barely affect the PED **(verified)**. The PED's shape is set
  by the inner TS. The prompt code takes the zero of the available energy from the **bimolecular
  product `GroundEnergy`**, not from the fake well.

---

## 1. What a fake well looks like in a MESS input

Example: `2-H_C4H71-3/mess.inp` (C4H8-2 + H → C4H71-3 + H2), energies in kcal/mol:

```
C4H8-2+H ─FakeRB3─ FakeW-C4H8-2+H ─ts_2_3─ FakeW-C4H71-3+H2 ─FakePB3─ C4H71-3+H2
  0.00     0.00 (PST)    -1.00       +7.25 (Eckart)  -19.34      -18.34 (PST)   -18.34
```

The MESS blocks that make up one fake side:

| block | MESS keyword | content |
|---|---|---|
| fake well | `Well FakeW-A+B ! Fake Well for A+B` | RRHO species: joined geometry, `RigidRotor` core, symmetry factor = product of the fragments' factors, combined electronic levels, dummy intermolecular frequencies + all fragment frequencies, all fragment hindered rotors; `ZeroEnergy` = asymptote − depth |
| fake barrier | `Barrier FakeB-A+B A+B FakeW-A+B` (older labels: `FRB<n>`, `FPB<n>`, `FakeRB<n>`, `FakePB<n>`) | `Core PhaseSpaceTheory` with `PotentialPrefactor[au] 10.0`, `PotentialPowerExponent 6.0` (C6/R^6), both fragment geometries, fragment frequencies and rotors; `ZeroEnergy` = asymptote energy |
| inner TS | `Barrier ts_x_y FakeW-A+B FakeW-C+D` | the real saddle point, reconnected to the two fake wells instead of the bimolecular species; Eckart `WellDepth`s are measured from the fake-well energies |

---

## 2. Writing side: mechdriver + automol (current version)

### 2.1 When fake wells are created

- Model keys `ts.rwells` and `ts.pwells` take the values `fake` | `find` | `none`; the default is `fake`
  (`mechdriver/src/mechlib/amech_io/parser/models.py:85-86`).
- `need_fake_wells(reagents, well_model)` returns `well_model == 'fake' and len(reagents) == 2`
  (`mechdriver/src/mechroutines/models/typ.py:127-140`).
- It is called on the reactant side and on the product side of each channel
  (`mechdriver/src/mechroutines/ktp/rates.py:832-838`). When true, the side's species data are copied
  to `chnl_infs['fake_vdwr']` or `chnl_infs['fake_vdwp']`.
- **Since 2024-04-20, every bimolecular side of every channel gets a fake well** when the model is
  `fake`, whatever the reaction class **(code reading)**. Before that, only H-abstractions and
  substitutions did (see §5).
- `find` is accepted by the parser but **not implemented**: nothing checks for it, so it behaves
  like `none` **(code reading)**.

### 2.2 Energies (`mechdriver/src/mechroutines/ktp/_ene.py:98-107`)

```python
vdwr_ene = reac_ene - (3.0 * phycon.KCAL2EH)   # fake well
{'fake_vdwr': vdwr_ene, 'fake_vdwr_ts': reac_ene}  # fake PST barrier at the asymptote
# same for the product side ('fake_vdwp', 'fake_vdwp_ts')
```

- Fake well = asymptote − 3 kcal/mol (it was −1 kcal/mol before 2022-11-01).
- Fake PST barrier = asymptote energy exactly.

### 2.3 Labels and MESS strings (`mechdriver/src/mechroutines/ktp/rates.py:687-767`)

- Fake well label: `make_rxn_str(side_reagents, prepend='FakeW-')`, i.e. `FakeW-A+B` (line 731).
  `make_rxn_str` is simply `prepend + '+'.join(rlst)` (`mechroutines/models/inf.py:6-9`).
- Aux comment: `! Fake Well for A+B`.
- Fake barrier label: `FakeB-A+B` (line 755). It connects the real bimolecular label to the fake well.
- PST parameters: `{'n_pst': 6.0, 'cn_pst': 10.0}` (lines 713-716), giving
  `PotentialPowerExponent 6`, `PotentialPrefactor 10 au`.
- The inner TS label is relabelled to connect the two fake wells (`inner_reac_label = fake_lbl`, line 550;
  `inner_prod_label = fake_lbl`, line 569).
- Duplicate guard: a fake well and its barrier are written only once per PES (`written_labels`, lines 544-547 and 563-566).
  Several channels sharing the same bimolecular pair therefore share one fake well.

### 2.4 The fake species block (`mechdriver/src/mechroutines/models/blocks.py:167-215`)

- Geometry: `automol.combine.fake_vdw_geometry(*geos)` → `geom.join_sequence` → `geom.join`
  (`autochem/src/automol/geom/base/_0core.py:884-946`). Each fragment is mass-centred, then the next
  fragment is placed along +z until the closest intermolecular atom–atom distance is about 3 Å.
  - Example: in `H_C4H71-3/mess.inp` the H atom sits at z = 4.49 Å, about 3.4 Å from the nearest H of C4H8.
- Symmetry factor: product of the fragment symmetry factors.
- Electronic levels: `automol.combine.electronic_energy_levels`, i.e. all combinations, energies summed,
  degeneracies multiplied, duplicates merged.
- Frequencies: `fake_vdw_frequencies(*geos)` followed by all fragment frequencies.
  - Current rule (`autochem/src/automol/combine.py:26-34`): `nfake = Σ external modes of the fragments − external modes of the complex`,
    with 6 external modes for a nonlinear fragment, 5 for a linear one, 3 for an atom.
  - Every dummy mode is set to **200 cm⁻¹**.
  - Example: nonlinear + atom → 3 modes; nonlinear + linear → 5; nonlinear + nonlinear → 6.
- Hindered rotors: the fragment rotor strings are concatenated, so the fragment torsions are kept unchanged.

### 2.5 Tunnelling (`mechdriver/src/mechroutines/models/tunnel.py:65-79`)

- If a fake well exists on a side, the Eckart well depth on that side is `E_TS − E_fakewell`
  (not `E_TS − E_asymptote`). Each depth is floored at 0.1 kcal/mol.
- Since 2025-09-26 (`7f0e6838`) the tunnelling block is not written when either barrier height is below 0.1 kcal/mol.
- Consequence: **the fake-well depth enters k(T) through the tunnelling correction.**
  - With 1 kcal/mol depth: `WellDepth = 8.25 / 26.59` in `2-H_C4H71-3`.
  - With 3 kcal/mol depth each value would be 2 kcal/mol larger.

---

## 3. Reading side: mess_io (current version)

All fake-well handling in the reader is **string-based**.

### 3.1 Rate constants: `filter_rxn_ktp_dct` (`autoio/src/mess_io/reader/rates.py:710-797`)

- It is called from `get_rxn_ktp_dct(..., filter_reaction_types=...)` when `'fake'` is in the list.
- The default list is `UNWANTED_RXN_TYPS = ('fake', 'self', 'loss', 'capture', 'reverse')` (line 19).

Algorithm, for each MESS reaction `(rct, prd)`:

1. Drop it if the product is `Loss` or `Capture` (when those filters are on).
2. Drop it if `rct == prd` (self).
3. Drop it if it is not the "desired direction" (`is_desired_direction`, which compares forward and
   backward k at 1000 K and 1 atm). Note that this happens *before* the fake test.
4. **Fake test:** does any reactant or product label contain `'Fake'`? The test uses the MESS output
   name, or the translated name if the output has a names-translation table.
   - If yes, and a **product** contains `'Fake'`: stash the reaction in `fake_rxn_ktp_dct`.
   - In both cases the reaction is removed from the main dictionary.
5. After the loop, for each stashed reaction:
   - Strip `FakeW-` (or `FW-`) from **every** species name: `A+B → FakeW-C+D` becomes `A+B → C+D`.
   - If that real reaction survived the filtering: delete the stashed reaction's `'high'` entry, then add
     its remaining pressure entries to the real reaction (`add_ktp_dcts`, which takes the union of the
     T grids). The real reaction's own `'high'` value is kept unchanged.
   - If the real reaction is not in the dictionary, the stashed rates are dropped.

What this means:

- `FakeW-X → anything` with a real product: **discarded**. This is what the commit message calls
  "FakeW reactants skipped".
- `real → FakeW-Y`: **merged into `real → Y`** at finite pressure. The physical reading is that
  population stabilised in the product fake well is really separated products.
- High-pressure limit: only the real reaction's value is kept.

**In the runs of this folder the merge never adds anything (verified).** MESS never keeps the fake
wells as separate species in the pressure-dependent tables: every fake-well column is `***` at every
T and P. The only finite-pressure fake-well entries are `FakeW-X → Capture`, which the capture filter
removes. The fake-well rates appear only in the high-pressure tables, where they are discarded.
Running the reader on `2-H_C4H71-3/rate.out` returns exactly one reaction:
`(('C4H8-2','H'), ('C4H71-3','H2'))`.

### 3.2 Other readers

| what | where | treatment |
|---|---|---|
| PED (`ped.out`) | `autoio/src/mess_io/reader/ped.py:234-239` | any PED whose label contains `FakeW` is skipped |
| PED energy zero | `ped.py:257,286` + `reader/_nonboltz.py:13` | `energy = E_ped + ene0` with `ene0 = −energy_dct[products]`; `energy_dct` comes from `reader.pes(inp)` with `read_fake=False`, so it is the **bimolecular `GroundEnergy`** |
| hot-energy branching (`mess.log`) | `autoio/src/mess_io/reader/hoten.py:64-65,188-191` | column `FakeW-X` is added to column `X`, then dropped |
| well extension | `autoio/src/mess_io/_wellextend.py:117-119` | wells named `FakeW…` get `WellExtensionCap = None`, so no cap is written |
| PES reader | `autoio/src/mess_io/reader/_pes.py:44,118,128-131` | with `read_fake=False` (default), any well or barrier label **containing a capital `F`** is skipped; connection labels have `F` replaced by `P` |
| label list | `autoio/src/mess_io/reader/_label.py:116-130` | with `read_fake=False`, labels containing `F` **or `f`** are dropped |
| xarray WIP reader | `autoio/src/mess_io/reader/new_rates.py:720` | drops any reaction whose label contains `Fake`; no merge |

### 3.3 Who calls the fake filter

- `mechanalyzer/src/mechanalyzer/builder/_prompt.py:39-44`: all PESs listed in `prompt.py` (`FLDs`),
  filters `('fake','self','loss','capture','reverse')`.
- `mechanalyzer/src/mechanalyzer/calculator/nonboltz.py:39-44`: the PED PES; `'reverse'` is not filtered
  there, and backward reactions are removed afterwards with `remove_rev_rxns`.
- `mechdriver/src/mechroutines/ktp/_multipes.py:225-229`: multi-PES fitting inside mechdriver.

### 3.4 Things that are *not* about fake wells (name clashes)

- `mechanalyzer/parser/_util.py: remove_fw_rxns`: here `fw` means *forward*.
- `mechanalyzer/builder/sort_fct.py: 'WELLSKIPPING FAKE'`: placeholder reactions added by the
  well-skipping generator. These are unrelated to MESS fake wells.

---

## 4. Effect on prompt dissociation (this folder)

### 4.1 PED

Analysed at 500 K and 0.03 atm with `test_change_prodEN/*/2-H_C4H71-3/ped.out` **(verified)**:

- The PED energies are absolute (zero = reactants). The shape is set by the thermal flux through the
  inner TS `ts_2_3` (7.25 kcal/mol): peak at 12.7 kcal/mol, mean 14.39 kcal/mol.
- Moving the product fake well and fake barrier together with the products changes nothing above
  E = 0 (agreement within about 1 %). The only change is where the energy grid stops at low energy,
  which is the exit PST barrier energy (−18.3, −20.2 or −16.3).
- The part of the PED below 0 kcal/mol carries about 2×10⁻⁷ of the total weight.
- The prompt code then computes `E_avail = E − GroundEnergy(C+D)` and splits it between the fragments
  with the chosen model.

### 4.2 Energy-shift tests

The C4H7 hot-PES inputs are byte-identical across these tests, so only the H-abstraction PES differs.

| test | products | product fake well | exit fake barrier | extra energy for products | stabilised C4H71-3 (1500 K, 0.03 atm) |
|---|---|---|---|---|---|
| higheren_fakew_andprds | −16.34 | −17.34 | −16.34 | −2 | 0.167 |
| base_newmess | −18.34 | −19.34 | −18.34 | 0 | 0.138 |
| loweren_fakew_andprds | −20.34 | −21.34 | −20.34 | +2 | 0.112 |
| loweren | **−22.34** | −19.34 | −18.34 | **+4** | 0.089 |

The four points lie on one smooth curve: only the product energy relative to the fixed TS matters.

Corrections to `instructions.txt`:

- `loweren` lowers the products by **4** kcal/mol, not 2.
- Test 2 gives less prompt dissociation than test 1 because its shift is 2 kcal/mol, not 4. The extra
  low-energy points in its PED carry about 10⁻⁷ of the weight and are not the cause.

---

## 5. Version history

### 5.1 Writing side (mechdriver, automol)

| date | commit (author) | change |
|---|---|---|
| 2019-09-27 | `a8c7b528` (S. Elliott), mechdriver (then `moldr/pf.py`) | fake wells introduced |
| 2019-09-28 | `67848b72` (S. Klippenstein) | "fake wells and PST debugged" |
| until 2022-03 | (several) | **index labels**: fake wells `F<n>`, PST fake barriers `FRB<n>` / `FPB<n>`, assigned through a `label_dct`. The legacy code is still in `mechdriver/src/mechroutines/ktp/label.py:99-144` |
| 2022-03-03 | `28e10508` (K. Moore) | **descriptive labels**: fake wells `FW-A+B`; fake barriers still `FRB<chn>` / `FPB<chn>` |
| 2022-04-26 | `884e5478`, `16697bb6` (K. Moore) | `FW-` → **`FakeW-`**; `FRB`/`FPB` → **`FakeRB<chn>` / `FakePB<chn>`** |
| 2022-11-01 | `4c2cef1e` (S. Klippenstein) | fake-well depth **1 → 3 kcal/mol** (`_ene.py`) |
| 2024-04-20 | `ca54ce0a` (cmulvihill) | fake-barrier label **`FakeB-A+B`**; trigger changed from reaction class (`requires_well_description` = H-abstraction or substitution) to **any bimolecular side**; duplicate fake blocks no longer written |
| until 2024-06-21 | automol `combine.py` | dummy frequencies `[30, 50, 70, 100, 200][:ntrans]` with `ntrans = 5 − 3·(atoms) − 2·(linear fragments)`. This **undercounts** the intermolecular modes by 1–2 (nonlinear + atom → 2 instead of 3; nonlinear + linear → 3 instead of 5; nonlinear + nonlinear → 5 instead of 6) |
| 2024-06-21 | `91d2dfa1` (A. Copan), autochem | correct mode count, generalised to 3+ fragments; values `10, 20, 30, …` cm⁻¹ |
| 2025-09-26 | `1af132bc` (A. Copan), autochem | all dummy modes set to **200 cm⁻¹** ("to avoid low values") |

### 5.2 Reading side (autoio / mess_io)

| date | commit (author) | change |
|---|---|---|
| 2020-09-11 | `506f543` (K. Moore) | `_pes.py`: skip labels containing `F` unless `read_fake=True` |
| 2021-04-16 | `87dd323` (K. Moore) | label reader (now `_label.labels`): drop labels containing `F` or `f` unless `read_fake=True` |
| 2022-03-15 | `e4ab916` (K. Moore) | `filter_fake` option added to the k(T,P) filter. Just before 2022-04-26 the test was `'F' in label or 'FW' in label` → drop |
| 2022-04-26 | `7310751` (K. Moore) | test changed to **`'Fake' in label`** only. From here on, old `FW-` / `F<n>` labels are no longer recognised as fake |
| 2023-04-11 | `3a830cf` (cmulvihill) | reaction-direction handling in mess_io, around the same filter code |
| 2024-11-14 | `327bc0f` (L. Pratali Maffei) | **merge**: stash reactions with a fake product, strip `FakeW-` / `FW-`, add to the real reaction (finite P only, real high-pressure limit kept); fake-reactant reactions discarded; hot-energy branching fractions of `FakeW-X` added to `X`; PEDs with `FakeW` skipped; also uses the translated name when a names table exists |
| 2024-11-14 | `10f8cc1` (L. Pratali Maffei) | `_wellextend.py`: no `WellExtensionCap` for `FakeW` wells |
| 2024-12-03 | `96e02b4` (yokochin) | `new_rates.py` (xarray, work in progress): drop `Fake` reactions, no merge |
| 2025-09-17 | `efcc993` (L. Pratali Maffei) | hot-energy reader: fake → real map built from the full species list (fix for partially stable wells) |

### 5.3 Telling which version produced a MESS input

| fingerprint | era |
|---|---|
| fake well `F<n>`, barriers `FRB<n>` / `FPB<n>` | before 2022-03-03 |
| fake well `FW-A+B`, barriers `FRB<n>` / `FPB<n>` | 2022-03-03 → 2022-04-26 |
| fake well `FakeW-A+B`, barriers `FakeRB<n>` / `FakePB<n>` | 2022-04-26 → 2024-04-20 |
| fake barrier `FakeB-A+B` | after 2024-04-20 |
| depth 1 kcal/mol | before 2022-11-01 (3 kcal/mol after) |
| dummy freqs 30/50/70… (undercounted) | before 2024-06-21 |
| dummy freqs 10/20/30… | 2024-06-21 → 2025-09-26 |
| dummy freqs all 200 | after 2025-09-26 |
| fake wells on non-abstraction / non-substitution channels | after 2024-04-20 |

The inputs in this folder, matched against the upstream history:

| folders | labels | depth | dummy freqs | consistent with upstream era |
|---|---|---|---|---|
| `H_C4H71-3`, `H_C4H71-4`, `OH_C4H71-3`, `OH_C4H71-4` | `FW-`, `FRB<n>` / `FPB<n>` | 1 kcal/mol | old rule (see below) | Mar–Apr 2022 |
| `2-H_C4H71-3`, `2-OH_C4H71-3`, `2-O_C4H71-3` (and `test_change_prodEN/*`) | `FakeW-`, `FakeRB3` / `FakePB3` | 1 kcal/mol | old rule (see below) | Apr–Nov 2022 |

Every fake well in these folders follows the pre-June-2024 frequency rule exactly **(verified)**:

- 30/50 cm⁻¹ with an atom partner (`+H`, `+O`);
- 30/50/70 with a linear partner (`+H2`, `+OH`);
- 30/50/70/100/200 with `+H2O`.

These eras are inferred from the upstream history only. The inputs could also come from a fork that
mixed these features differently.

---

## 6. Pitfalls and open points

1. **`FW-` labels leak through the current reader (verified).** The gate tests for `'Fake'`, which
   `FW-…` does not contain. The `FW-` branch in the prefix stripping (`rates.py:770-775`) is therefore never reached.
   - On `H_C4H71-3/rate.out` the filtered result contains six reactions, five of them involving
     `FW-` wells. Three have only high-pressure data and two are empty:
     `FW-C4H8-1+H → FW-C4H71-3+H2`, `FW-C4H8-1+H → C4H71-3+H2`, `FW-C4H71-3+H2 → C4H8-1+H`,
     `C4H8-1+H → FW-C4H8-1+H`, `C4H71-3+H2 → FW-C4H71-3+H2`.
   - **They do reach the final rate file with the current code (verified 2026-10-01).** Rerunning
     `prompt.py` with the current `FLDs` in an `automech` conda env (with mechanalyzer installed)
     writes **10 spurious reactions** to `rates_equip_simple.txt`, fitted from high-pressure values only,
     for example `C4H8-1 + H = FW-C4H8-1 + H` and `FW-C4H8-1 + H = FW-C4H71-3 + H2`.
     - The existing `rates_equip_simple.txt` in this folder has none, so it was made with older code.
     - The 20 real reactions are reproduced to within 0.7 %.
   - Fix: rename `FW-` → `FakeW-` in old inputs **before running MESS** (the reader parses the labels in
     `rate.out`), or delete the `FW-` reactions from the rate file afterwards, or extend the gate to `'FW-'`.
2. **`FakeW-A → FakeW-B` would be merged into `A → B` (code reading, not triggered here).**
   - The stash condition only asks that the *product* be fake, and the stripping applies to both sides.
   - Labels like `FakeW-C4H8-2+H` contain `+`, so `ktp_dct` treats them as bimolecular
     (`bimol = reactant[0] == 'P' or '+' in reactant`, `rates.py:119`) and multiplies the k by Avogadro's number.
   - If MESS ever printed finite-pressure `FakeW → FakeW` rates (deeper wells, low T, high P), a
     unimolecular k with wrong units would be added to a bimolecular k.
   - None of the outputs in this folder has such entries.
3. **The `'F'` rule in `_pes.py` and `_label.labels` is too broad.** Any real species or barrier label
   containing a capital `F` (fluorine species, for example) is treated as fake and dropped from
   `energy_dct`. That would break the PED energy zero for such products.
4. **Editing fake-well energies by hand:**
   - Move `GroundEnergy`, the fake well `ZeroEnergy` and the fake barrier `ZeroEnergy` together,
     and update the Eckart `WellDepth` of the inner TS.
   - The `test_change_prodEN` inputs kept `WellDepth 26.59`; the consistent values are 28.59 and 24.59.
   - Lowering only `GroundEnergy` (the `loweren` test) leaves a 4 kcal/mol artificial exit barrier
     (fake barrier above products). Every product then gets at least 4 kcal/mol by construction.
5. **`rwells` / `pwells = find`** is accepted but does nothing. Real vdW wells must be written into the MESS input by hand.
6. **Physical caveat.** For OH abstractions a real pre-reactive complex is expected (OH + alkenes
   typically form one a few kcal/mol deep). The fake well stands in for it only approximately:
   its depth and modes are arbitrary, and the depth enters k(T) through the Eckart well depths.
7. **Current defaults vs. this folder's inputs.** Regenerating these inputs with the current code would
   change the depth (1 → 3 kcal/mol), the dummy modes (30/50/70 → 200 cm⁻¹, correct count) and the
   labels (`FakeRB3` / `FakePB3` → `FakeB-…`). Given how little the fake wells affect the PED, the PED
   should not change. k(T) should change slightly through the Eckart depths **(not verified)**.

---

## 7. Quick file index (current checkout)

| topic | file |
|---|---|
| model keys `rwells` / `pwells` | `mechdriver/src/mechlib/amech_io/parser/models.py:85-86` |
| trigger | `mechdriver/src/mechroutines/models/typ.py:127-140`, `mechdriver/src/mechroutines/ktp/rates.py:832-838` |
| energies | `mechdriver/src/mechroutines/ktp/_ene.py:98-107` |
| MESS strings, labels, PST params | `mechdriver/src/mechroutines/ktp/rates.py:535-574, 687-767` |
| fake species block | `mechdriver/src/mechroutines/models/blocks.py:167-215` |
| Eckart depths | `mechdriver/src/mechroutines/models/tunnel.py:65-79` |
| legacy `F<n>` / `FRB` / `FPB` label code | `mechdriver/src/mechroutines/ktp/label.py:99-144` |
| geometry join | `autochem/src/automol/geom/base/_0core.py:884-946` |
| dummy frequencies, electronic levels | `autochem/src/automol/combine.py:21-34` and following |
| k(T,P) fake filter and merge | `autoio/src/mess_io/reader/rates.py:710-797` |
| PED skip and energy zero | `autoio/src/mess_io/reader/ped.py:234-286`, `autoio/src/mess_io/reader/_nonboltz.py:13` |
| hot-energy merge | `autoio/src/mess_io/reader/hoten.py:64-65, 188-191` |
| well-extension skip | `autoio/src/mess_io/_wellextend.py:117-119` |
| `'F'` label rule | `autoio/src/mess_io/reader/_pes.py:44,118`, `autoio/src/mess_io/reader/_label.py:116-130` |
| prompt-workflow callers | `mechanalyzer/src/mechanalyzer/builder/_prompt.py:39-44`, `mechanalyzer/src/mechanalyzer/calculator/nonboltz.py:39-44,81` |
