---
name: prompt-branching-fractions
description: "How the C4H8/C4H7 paper computes prompt branching fractions and prompt rate coefficients — data taken from each PES, models, Eq. 9 convolution, k = BF·k1, product renaming/summing, mapped to mechanalyzer/mess_io code"
metadata:
  node_type: memory
  type: project
  originSessionId: cb7d02e6-bd70-45fe-beb6-84d0c0475394
  modified: 2026-10-01T22:31:55.652Z
---

Summary written 2026-10-01 from the paper (see [[prompt-paper-reference]]), `non-thermal-sop.md`, and the code in `/data/home/csoulie/automech/` (paths below are relative to it). System map: [[c4h8-prompt-system-map]].

**Why:** this is the reasoning behind every `prompt.py` run and every file in `RATE CONSTANTS/`; it took reading the paper and the code together to work out.
**How to apply:** use it when explaining, checking or extending prompt results (new abstractors, other models, thresholds). Check line numbers against the code before quoting them; they were correct on 2026-10-01.

## 1. Non-thermal rate coefficients computed in the paper

```
(1) R1 + R2 → I1* + I2        abstraction, k1 (the usual thermal rate constant)
(2) I1* (+M) → I1 (+M)        collisional stabilisation
(3) I1* → P1 + P2             prompt dissociation (or isomerisation)
⇒ (4) R1+R2 → I1 + I2         and   (5) R1+R2 → P1 + P2 + I2,     with k1 = k4 + k5
```

A prompt rate coefficient is k1 split by T- and P-dependent branching fractions (BFs). There are no new rate constants beyond k1. A pressure-independent abstraction becomes a set of pressure-dependent channels.

- **Validation cases (BFs only):**
  - CH2O + H → HCO* + H2 → H + CO, compared with trajectory results.
  - C3H8 + H/OH → n-/i-C3H7* → C2H4 + CH3, etc., using Danilack and Goldsmith's MESS inputs.
- **Application, C4H7:**
  - Selection: 84 reactions forming C4H71-3 or C4H71-4 in C3MechV3.3. Keeping ΔH1+ΔH3 ≤ 30 kcal/mol left 17. Twelve were computed: abstraction by H, CH3, OH and O(3P) from C4H8-1 secondary site → C4H71-3, C4H8-1 primary site → C4H71-4, and C4H8-2 → C4H71-3.
  - Abstraction rates: AutoMech, B2PLYP-D3/cc-pVTZ geometries and CCSD(T)-F12 energies, conventional TST with Eckart tunnelling.
  - C4H7 decomposition PES: Li et al., with well extension and α = 100·(T/300)^0.8 cm⁻¹ in N2.
  - Each abstraction is split into 4 products: thermalised C4H71-3, thermalised C4H71-4, C4H6+H and C2H4+C2H3. After summing duplicates this gives **32 reactions**, over 500–2500 K and 0.03–100 atm, fitted as PLOG.
  - Mechanism versions: base, thermal model, ρDOS model = `RATE CONSTANTS/base.txt`, `prompt_thermal.txt`, `prompt_rovib_dos.txt`. Verified: `prompt_rovib_dos.txt` contains exactly these 32 reactions.

## 2. Prompt branching fractions

### 2.1 What is taken from which PES

| From | File | What is read | Code |
|---|---|---|---|
| **Abstraction PES** (e.g. `H_C4H71-3`, PES 2:1) | `mess.inp` | `PEDSpecies` (which product is hot); energies (reactants 0, products `GroundEnergy`) → energy zero and exo/endothermicity check; species blocks → degrees of freedom and masses | `ped.ped_names`, `reader.pes`, `spinfo_frommess.get_info` |
| | `ped.out` | α(E): distribution of the total energy of the C4H71-3* + H2* pair, at every T,P | `mess_io/.../ped.py:get_ped` |
| | `ke.out` | ρ(E) of each product fragment (needs the `density` keyword) | `rates.dos_rovib` |
| | `rate.out` | k1(T,P) of C4H8-1 + H = C4H71-3 + H2 | `rates.get_rxn_ktp_dct` |
| **C4H7 PES** (PES 1, `C4H7_JC/wellcap_eigmax02`) | `mess.inp` | `HotEnergies` species (C4H71-3, C4H71-4); well energies (−45.63, −28.82 kcal/mol); fragment names of the bimolecular products | `hoten.get_hot_species`, `dct_species_fragments` |
| | `mess.log` | "hot energies branching fractions": for each T,P, each hot well and each starting energy E′, the fraction going to C4H71-3, C4H71-4, C4H6+H and C2H4+C2H3 | `hoten.extract_hot_branching` |
| | `rate.out` | Thermal C4H7 rates, copied unchanged into the final file | `_prompt.py` |

- **Linking the PESs:** a PED product name must equal a `HotEnergies` species name (`nonboltz.py:74`). That match picks the hot fragment I1 = C4H71-3. The other fragment I2 (H2, H2O, OH or CH4) is assumed thermalised.
- **`density` keyword:** needed on both product fragments of every PED (abstraction) input, whatever `-m` model is chosen. `ped_info` always calls `rates.dos_rovib`, which raises IndexError if `ke.out` has no "Bimolecular fragments density of states" section. Only `rovib_dos` (ρ1, ρ2) and `thermal` (ρ1) use the numbers. Columns `<Bimol>_0/_1` are named by splitting the Bimolecular name on '+', so that name's order must match the order of the Fragment blocks (code inference; a mismatch would swap the columns silently). The C4H7 hot input needs none. Verified 2026-10-01: all 11 `ME_INPUT` abstraction inputs have 2 density fragments.
- In this system, the 12 abstraction folders are "ped" type and C4H7 is "hot" type. Only the simple ped → hot branch of `builder/_prompt.py:rxn_chains_calc` is used; the multi-PES chain code is not exercised.

### 2.2 Step 1: α(E) from the abstraction PES (paper Eq. 7 input)

File format and typical values: [[ped-output-file]].

- MESS writes the PED on the abstraction PES's energy scale. `get_ped` shifts it by −E(products) (`ped.py:257`), so E is the energy above the C4H71-3 + H2 asymptote.
- Example, `H_C4H71-3`: the TS is at +5.87 kcal/mol and the products at −19.95, so the backward barrier is 25.8 kcal/mol (the "Ebw 26" in the paper's Fig. 5c). α(E) sits near Ebw plus thermal energy.
- An endothermic abstraction forces the thermal model (`nonboltz.py:81-89`).

### 2.3 Step 2: split the energy between the fragments → f(E′)

```
f(E') = ∫_{E'}^{Emax} α(E)·β(E';E) dE   / normalisation                       (Eq. 7)
```

The `-m` option chooses β (`calculator/ene_partition.py`, class `PEDModels`):

| `-m` | Paper | What it does |
|---|---|---|
| `thermal` | Eq. 10 | f(E′) = ρ_C4H71-3(E′)·exp(−E′/kT), normalised. Ignores α, so it is the same for every abstractor; reproduces MESS 1−f_ne. Lower bound on prompt effects. |
| `equip_simple` | Eqs. 11–12 | φ = (Nvib1 + Nrot1/2)/(Nvib1 + Nvib2 + (Nrot1 + Nrot2 + 3)/2), then α rescaled to E′ = φE. φ ≈ 0.89 with H2, 0.70 with CH4. `prompt.py` default. |
| `equip_phi`, `beta_phi1a/2a/3a` | Eq. 13 | Gaussian β centred at φE, σ = 0.87 + 0.04E; φ from equipartition or Danilack–Goldsmith φ1a/2a/3a |
| `rovib_dos` | Eqs. 14–15 (ρDOS, the paper's new model) | β(E′;E) = ρ1(E′)·ρ̄(E−E′) / ∫₀ᴱ ρ1·ρ̄, with ρ̄(y) = ∫₀ʸ ρ2(z)·ρtr(y−z) dz and ρtr ∝ μ^{3/2}·y^{1/2} (`init_dos`, `dos`, `dos_trasl`) |

With ρDOS, the fraction of energy given to C4H71-3 depends on T and on the partner fragment: for CH4 it is about 81% at 1000 K versus a fixed 70% for equipartition, because CH4's high-frequency modes take little energy. ρ1 and ρ2 come from the abstraction PES's `ke.out`.

### 2.4 Step 3: energy-resolved BFs from the C4H7 PES (paper Eq. 8)

- `HotEnergies` (`C4H71-3 -45:1:250`, `C4H71-4 -28:1:230`) makes MESS start a delta-function population of each well at each energy, then report where it ends up:
  - isomerisation fractions by projection onto the chemical eigenspace;
  - dissociation fractions by time integration over the relaxation eigenstates.
- The reader subtracts the well energy (`hoten.py:145`), so E′ is measured from the well bottom; only E′ > 0 is kept.
- Example rows in the log (500 K, 0.03 atm):
  - C4H71-3 at 79.4 kcal/mol above its well: 0.968 → C4H6+H, 0.032 → C2H4+C2H3.
  - C4H71-4 at 62.6 kcal/mol: 0.70 / 0.30.
  - C4H71-4 at 23.9 kcal/mol (below its 28.8 kcal/mol threshold): BF = 1 to C4H71-4.
- **Inference (not stated in the paper):** the two PESs are coupled only through the radical's internal energy above its ground state (`ke.out` DOS grid on one side, energy above the well on the other). Their absolute energies need not agree, which matters because they come from different levels of theory (AutoMech vs Li et al.).

### 2.5 Step 4: convolution (paper Eq. 9), `calculator/bf.py:bf_tp_df_full`

```
BF_{R→Pi+I2}(T,P) = ∫ f(E')·BF_{I1*→Pi}(E') dE'  /  Σ_j ∫ f(E')·BF_{I1*→Pj}(E') dE'
```

- At each T,P: hot energies restricted to f's range (≥ 4 points required); each BFᵢ(E′) cubic-interpolated onto f's grid, held constant beyond the ends, trapezoid-integrated (`bf.py:169`); negative noise values replaced by absolute values; normalised over the 4 products (`bf.py:176`).
- **Threshold (`-b`):** a product is kept if BF ≥ threshold at **at least one** T,P point (`bf.py:231-238`); dropped only if below it everywhere.
- The paper used no filtering → 32 reactions. A 1% threshold gives 28 (the C4H8-2 → C4H71-4 isomerisation channel drops out). `prompt.py` defaults to 0.01, so it would drop those channels.

## 3. From branching fractions to prompt rate coefficients

1. **Multiply** (`bf.py:merge_bf_rates`), at each pressure and common temperature:
   ```
   k_{R→Pi+I2}(T,P) = BF_{R→Pi+I2}(T,P) · k1(T,P)        (k1 from the abstraction rate.out)
   ```
   The BFs sum to 1, so the total abstraction rate is unchanged, only redistributed. Almost all pressure dependence comes from the BFs.
2. **Rename** (`bf.py:rename_ktp_dct`):
   - product = hot species → original name kept (`C4H8-1+H=C4H71-3+H2`, now BF-scaled);
   - otherwise C4H71-3 is replaced by Pi's fragments from the C4H7 input: `C4H8-1+H → H2+C4H6+H`, or `→ H2+C4H71-4` for prompt isomerisation.
3. **Sum duplicates:** labels re-sorted, then `merge_rxn_ktp_dcts` adds k values with the same key. For C4H8-1 + H:
   ```
   k(C4H8-1+H = C4H71-3+H2)       = k₂:₁·BF⁽¹⁻³⁾[C4H71-3] + k₂:₂·BF⁽¹⁻⁴⁾[C4H71-3]   (thermalised + isomerised from C4H71-4*)
   k(C4H8-1+H = C4H71-4+H2)       = k₂:₁·BF⁽¹⁻³⁾[C4H71-4] + k₂:₂·BF⁽¹⁻⁴⁾[C4H71-4]
   k(C4H8-1+H => C4H6+H+H2)       = k₂:₁·BF⁽¹⁻³⁾[C4H6+H]  + k₂:₂·BF⁽¹⁻⁴⁾[C4H6+H]
   k(C4H8-1+H => C2H3+C2H4+H2)    = k₂:₁·BF⁽¹⁻³⁾[C2H4+C2H3] + k₂:₂·BF⁽¹⁻⁴⁾[C2H4+C2H3]
   ```
   BF⁽¹⁻³⁾ and BF⁽¹⁻⁴⁾ are the BFs of the hot C4H71-3 / C4H71-4 made by that abstraction, each with its own f(E′). For C4H8-2, k_i = k₂:₃·BF_i. Total: 4 abstractors × 2 butenes × 4 products = 32.
4. **Assemble:** original thermal abstraction entries and their reverses are replaced by the prompt versions; C4H7 PES rates (C4H71-3 = C4H6 + H, etc.) are kept unchanged.
5. **Write and fit:** three-product channels written as irreversible `=>` (`chemkin_io/writer/_util.py:97-105`); everything fitted with ratefit (single/double Arrhenius per pressure) → PLOG.

**Paper's conclusion with ρDOS:**
- Prompt effects significant from 1000 K; the thermalised-radical BF falls below 0.5 under 1500 K, giving up to an order of magnitude difference by 2000 K.
- Main product from C4H71-3* is C4H6 + H. C4H71-4* both dissociates and isomerises to C4H71-3 (up to 10% at 1000 K).
- The thermal model gives much smaller effects.
