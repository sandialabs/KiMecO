---
name: structure-based-species-names
description: "Why the structure-based (condensed-formula) MESS labels of the relabel-mess-by-structure skill are built the way they are, and the pitfalls of deriving connectivity from AutoMech MESS geometries (bond cutoff, H2 margin, TS and rotor geometries, fake wells, Atom fragments, SMILES comments). Read before changing relabel_mess.py or naming species from xyz."
type: project
verified: 2026-10-25 against working tree (skill relabel-mess-by-structure, uncommitted)
---
The rule and the CLI are in `.claude/skills/relabel-mess-by-structure/SKILL.md`; this note keeps the reasons and the pitfalls.

**Why the convention is what it is**
- Connectivity only, no `=`: mess_io splits `PEDSpecies` on `=` ([[mess-label-rules]]), and bond orders cannot be read from geometry (allylic C4H71-3 has C–C 1.379 and 1.381 Å; both its resonance SMILES give `CH2CHCHCH3`).
- Canonical direction = smallest ASCII string over the ends of every longest heavy-atom path; `(` < digits < letters, so `CH2CH2CHCH2` beats `CH2CHCH2CH2`. Branches: `CH3CH(CH3)CH3`.
- No radical or cis/trans marker: H counts already separate radicals from closed shells; two stereoisomers of one skeleton would get one name, which the collision check stops (its species key is the canonical isomeric SMILES of the AutoMech comment).
- ≤ 1 heavy atom keeps the usual formula (`OH`, `H2O`, not `HO`, `OH2`; note ASE's g2 formula string for OH is `HO`).
- `FakeW-<bimol>` and `<A>+<B>` are forced by mess_io. Barriers and saddle points are `<lside>=<rside>`: unique within a file (MESS allows one barrier per unordered pair), and the same phase-space barrier gets the same name in every file. Their uppercase `F` (from `FakeW-`) makes mess_io `_pes` treat saddle points as fake (accepted).
- No hashing of long labels: MESS has no label length limit, and the user's rule is to hash only if MESS limits length.
- Identity comes from the geometry and is cross-checked against AutoMech's SMILES comments (`! <smiles>` on every Fragment line, `! [<smiA> + <smiB>]` on every Bimolecular line), which also identify `Atom` fragments.

**Geometry pitfalls**
- Bond rule d ≤ 1.2·(r_i + r_j) with `ase.data.covalent_radii` (H 0.31, C 0.76, O 0.66 Å). H2 in AutoMech inputs is 0.740 Å against a 0.744 Å limit (0.004 Å margin); never loosen the rule silently.
- ASE `NeighborList` adds `skin` (default 0.3) to every radius, so its threshold is r_i + r_j + 0.6 Å; `natural_cutoffs` with `skin=0`, `mult=1` misses C–H at 1.09 Å (limit 1.07). automol uses max(Σ r_cov, mean r_vdW) × 1.05 plus a hypervalence fix. Three different answers near a cutoff.
- Saddle points: the transferred H sits 1.02–1.55 Å from both partners; under the 1.2 rule it stays on the donor (reactant connectivity). Never name a TS from its geometry; only its Hill formula is checked against its endpoints.
- AutoMech species blocks: the main geometry is the first `Geometry[angstrom]` right after `RRHO`, before any `Rotor`; `Rotor Hindered` blocks repeat a reoriented geometry (for fake wells, fragment A only). A fake well's geometry is fragment A's coordinates, then fragment B translated along +z (gap ≥ 3.2 Å), so it splits into exactly 2 molecules. Phase-space barriers have only `FragmentGeometry` blocks (bimolecular order) and rotor geometries.
- `Atom` fragments (`Atom`, `Mass[amu]`, `ElectronicLevels`) have no geometry: take the element from the mass, skipping `ase.data.atomic_masses[0]` (dummy `X`, mass 1.0); the phase-space barrier gives them a 1-atom `FragmentGeometry`.
- rdkit: `AddHs(MolFromSmiles('[HH]'))` gives 2 bonded H; `[H]` gives 1 atom plus the warning "not removing hydrogen atom without neighbors" (silenced with `RDLogger.DisableLog('rdApp.warning')`).

**Why:** each of these cost a design round or would silently give a wrong or non-unique name.
**How to apply:** read before extending the script (rings, real wells, hot PESs) or naming species another way; keep MESS paired runs (original vs renamed, identical rates) as the acceptance check.

Sources: `.claude/skills/relabel-mess-by-structure/relabel_mess.py` (`MolecularGraph`, `_SkeletonWriter`, `MessInputFile`, `Relabeler`); `ase/neighborlist.py::NeighborList.__init__` (`skin=0.3`); autochem `automol/util/heuristic.py`; the 2026-10-25 run on the C4H8 inputs ([[c4h8-prompt-system-map]]).
