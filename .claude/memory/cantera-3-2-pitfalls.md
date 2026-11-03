---
name: cantera-3-2-pitfalls
description: "Cantera 3.2 behaviours that bite KiMecO: Reactor contents= removed, the coming clone default, repeated species read as a three-body collider (dicts omit it), YAML vs object duplicate handling, and how KiMec builds its Solutions and adds species. Read before touching kinmec.py, the SIM templates, or comparing Cantera reactions."
type: reference
verified: 2026-11-03 against Cantera 3.2.0 (probes) + HEAD 56e465a with step 5 uncommitted
---
**Reactors.** `ct.ConstPressureMoleReactor(contents=gas)` raises `TypeError: __cinit__() takes at
least 1 positional argument` (the argument is now `phase`, no alias; positional also works).
`ReactorBase.thermo` is deprecated. Cantera 3.2 warns that **after 3.2 `clone` will default to
True**: the reactor would then work on a copy of `gas`, and KiMecO's templates, which read `gas.X`
after `net.advance`, would silently record the initial composition (pass `clone=False` or read the
reactor's phase). The warning lands in every SIM `.err`. The packaging still pins `cantera>=3.0.0`.

**Repeated species = three-body.** An equation with the same species on both sides and no
`type: elementary` becomes a three-body reaction with that species as collider (`three-body-Arrhenius`,
or `three-body-Mess-data` for KiMecO's custom rate): `CH4 + H => CH3 + H + H` has reactants `{CH4}`,
products `{CH3, H}`. `third_body` gives `name`, `mass_action`, `efficiencies`, `default_efficiency`
(generic `M`: `('M', True, {}, 1.0)`; named `X`: `(X, True, {X: 1.0}, 0.0)`; falloff `(+M)`:
`mass_action` False). With `type: elementary` the species stays (`CH4 + H => CH3 + 2 H`).
`Reaction.equation` is rewritten with species reordered; `forward_rate_constants` excludes [M], so the
rate is unchanged. Compare reactions by species multisets parsed from the equation, or put the
collider back; never by the dicts alone (KiMecO's `find_redundant_idx` does both, see
[[prompt-branching-fractions]] §4).

**Duplicates.** Loading YAML refuses undeclared duplicates (e.g. `CH3 + H2 <=> CH4 + H` with
`CH4 + H => CH3 + H2`) unless both carry `duplicate: true`; `ct.Solution(species=, reactions=[Reaction
objects])`, as KiMec builds its mechanism, accepts them and sums the rates.

**How KiMec builds Cantera objects.** Working and final Solutions use `thermo="ideal-gas",
kinetics="gas"` with no transport, so added species need no transport data (only the base YAML must
match its own phase `transport:`). `add_species` adds every missing SOP species, wells and fragments
(fragments are `Well` objects), with the NASA7 thermo of the base mechanism's `species[0]` (AR in
ThInK): harmless only because KiMecO reactions are irreversible and the templates run
`energy='off'`. `Well.compo` reads `structure.symbols`; an `Atom` fragment (H) has none, so a test
YAML should declare every SOP species.

**Why:** each of these broke or nearly broke step 5 of the prompt-reactions work (every SIM crashed
on `contents=`; a prompt `X + H => Y + Z + H` deleted an unrelated base `X => Y + Z`).
**How to apply:** check these before changing the templates, KiMec matching, or the Cantera pin.

Sources: Cantera 3.2.0 probes (env with cantera 3.2.0, 2026-11-02/03);
`kimeco/kinmec.py` (`KiMec.__init__`, `add_species`, `find_redundant_idx`, `_participant_species`),
`kimeco/templates/sim_arr_tpl.py`, `example/concentration_time_isobar_adiabatic.tpl`,
`kimeco/bimolecular.py`, `kimeco/well.py:Well.compo`, `tests/unit/test_cantera_templates_ci.py`.
