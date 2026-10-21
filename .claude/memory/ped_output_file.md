---
name: ped-output-file
description: "What a MESS ped.out (PEDOutput) file contains in the C4H8 prompt system — block layout, meaning of E, typical numbers, P-independence, and how mess_io turns it into α(E)"
metadata:
  node_type: memory
  type: project
  originSessionId: cb7d02e6-bd70-45fe-beb6-84d0c0475394
  modified: 2026-10-01T22:31:48.050Z
---

Written 2026-10-01 from inspecting `amech-dev/C4H8-prompt/H_C4H71-3/ped.out` and `mess_io/reader/ped.py:get_ped` (in `autoio/src/` of the AutoMech source checkout). How α(E) is used afterwards: [[prompt-branching-fractions]]. Which inputs have outputs: [[c4h8-prompt-system-map]].

**Why:** `ped.out` is the input to every prompt BF. Its energy zero and normalisation are easy to misread, and the energy shift applied when it is read explains the SOP's product-energy pitfall.
**How to apply:** use this when checking a new abstraction run (e.g. the CH3 inputs once they are run), when debugging odd BFs, or when changing product energies.

## What it is

Written by MESS when the global section has `PEDOutput ped.out` and `PEDSpecies <R>=<P>`. It holds the **total energy distribution of the product pair at the moment it is formed**, one distribution per (T, P). This is α_{R→I*}(E) in the paper (Eq. 7 input). It does **not** say how the energy is split between the two fragments (e.g. C4H71-3 vs H2); the `-m` partition model does that later.

## Layout

184 blocks = 23 temperatures × 8 pressures, with pressure changing fastest:

```
pressure[atm]        = 0.03
temperature[K]       = 500
energy step[1/cm]    = 69.5039          ← EnergyStepOverTemperature (0.2) × kT
maximum energy[1/cm] = 11768.7          ← top of MESS's energy grid at this T

Bimolecular-to-bimolecular product energy distributions:
  E, kcal/mol C4H8-1+H->C4H71-3+H2      ← one column per reaction listed in PEDSpecies
      33.6479            0.0011247      ← E (descending), relative probability
      ...
     -19.8076           8.2913e-11      ← stops just above the product asymptote (−19.95)
```

- **E** = total energy of the product system: both fragments' rovibrational energy plus their relative translation. It is on the abstraction PES scale (reactants' ground state = 0). The minimum is the product `GroundEnergy` (−19.95 kcal/mol for `H_C4H71-3`).
- **Probability:** MESS's distribution over energy of the reactive flux from reactants to products. The paper calls it the steady-state distribution "describing the system escape from R". The TS connects two fake wells, so the shape is essentially that of the flux through the TS.
- **Not unit-area in the file:** the integral is about 10 at 500 K and 68 at 2500 K. The reader renormalises each block.
- **Noise:** the low-energy tail has tiny negative values (~1e-9; 40 points at 500 K, 0.03 atm). They are numerical noise.
- **Other block types:** MESS can also print well-to-bimolecular blocks, and newer versions use "bimolecular PEDs / well PEDs / hot energy". The reader handles both formats; the abstraction inputs here only produce the bimolecular-to-bimolecular type.
- **Size:** about 1.5 MB here, but several GB for bigger systems (`non_thermal/ooqooh_ped.out` is 5 GB).

## Typical numbers (`H_C4H71-3`: TS +5.87, products −19.95 → backward barrier Ebw = 25.8 kcal/mol)

| T (K) | Peak E (PES scale) | Mean E | Mean E above products |
|---|---|---|---|
| 500 | 12.8 | 14.0 | 34.0 |
| 1000 | 33.5 | 35.7 | 55.7 |
| 1500 | 59.0 | 62.3 | 82.3 |
| 2000 | 87.4 | 91.4 | 111.3 |
| 2500 | 116.3 | 121.6 | 141.5 |

- Mean energy above products = Ebw + the thermal energy of the activated complex. The thermal part grows quickly with T because a 13-atom TS has many vibrations.
- **Pressure has essentially no effect:** at 0.03 vs 100 atm the peaks are identical and the means agree within 0.1 kcal/mol (the only wells are 1 kcal/mol fake wells). All the P dependence of the prompt BFs therefore comes from the C4H7 hot PES.

## How `get_ped` reads it

1. It shifts E by −`GroundEnergy` of the products, read from `mess.inp` (`ped.py:257`, +19.95 here). E becomes the energy available to the fragments, measured from the product asymptote.
2. It drops E ≤ 0 and duplicate energies, and renormalises each block to unit area. Negative noise values are kept, because `del_neg` is off by default.
3. It skips labels containing `FakeW`; old `FW-` labels are not caught (see [[automech-fake-wells-doc]]). It stores the result as `{((reacs),(prods),(None,)): DataFrame[T, P] → Series(E → prob)}`.

**Consequence (SOP pitfall 2):** the energies in `ped.out` stay on the PES scale and their shape is set by the TS. Lowering only the product energy leaves `ped.out` unchanged but moves the zero used in step 1, so the radical appears hotter and prompt dissociation increases.

The companion file `ke.out` holds the fragments' densities of states (needs the `density` keyword); details in [[prompt-branching-fractions]].
