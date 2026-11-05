---
name: mess-well-extension-caps
description: "How WellExtension, WellExtensionCap and ExtensionCorrection act in MESS, how mess_io derives caps from a first pass, what the KiMecO automech driver does with them, and the traps that give empty or wrong caps. Read before touching the two-pass driver or judging high-T rates of a PES with well extension."
type: reference
verified: 2026-11-05 against MESS c569e3a, autoio 0.2026.0 and the working tree (uncommitted well-extension-caps step)
---
**MESS (`src/libmess/mess.cc`, `src/mess_driver.cc`)**
- `WellExtensionCap` and `ExtensionCorrection` are read only inside `if(well_extension >= 0. && well_cutoff > 0.)` (`mess.cc:6282`), so without an active `WellExtension` line caps are inert. `ExtensionCorrection` acts only on a well with a cap (`mess.cc:6290`): on a pass without caps any change comes from `WellExtension` itself.
- `WellExtension`: value in [0, 1), bare keyword = 0, no "already set" check: the last line wins, so a later bare line silently sets 0 (`mess_driver.cc:947-965`).
- Any token starting with `!` or `#` is a comment and drops the rest of the line, no space needed (`io.cc:28,127-143`).

**mess_io (`_wellextend.py`)**
- `well_energies`: for each well, the highest T with a k at the reference pressure. If that is the run's top T: "No cap needed". Otherwise the cap is the thermal energy at that T, read from the log. So a first pass with `WellExtension` active gives no cap: its wells never vanish. A cap steps with the T grid and can change between models. `FakeW` wells never get one.
- Reference pressure match: keys are the printed 3-digit pressure times a unit factor (`out_precision = 3`, `model.cc:47`), compared with `isclose` rtol 1e-5 (l.172). A miss, or a well with no valid k there, falls back to the lowest T of the run (l.179) with one stdout line, `No k(T) values found`, and a far too low cap. Check that line before trusting a cap.
- `_format_well_extension_inp` uncomments by the literal text `!WellExtension`; `! WellExtension` takes the other branch, adds a bare line, and the value becomes 0.
- `well_lumped_input_file` works with `aux_str=''`. `merged_wells` needs `number of species =` in the `.aux`, printed only by `mess_2d.cc`, which `CMakeLists.txt` does not build: `mess` at c569e3a never gets a `LumpingScheme`. Older outputs do hold the line.
- `well_thermal_energy` crashes with an empty `.log` or no block at that T.
- mechdriver: writes `WellExtension 0.0010`, comments it for pass 1, always runs pass 2 when the task key is on, reads caps at `well_extension_pressure`, 1 atm by default (`mechroutines/ktp/rates.py:120-121,149,163`, `mechlib/amech_io/parser/models.py:19`).

**KiMecO driver (`kimeco/writers/automech_kin.py`)**
- Pass 1 comments the input's line (`_comment_well_extension`, raises if the line is missing); mess_io restores the value for pass 2; a PES without the key gets mess_io's bare line.
- Reference pressure: `min(grid_pres)` of the job, its sub-grid in postprocessing.
- The input's caps and `ExtensionCorrection` are not forwarded: `ExtensionCorrection 0.6` and computed caps are a user decision.
- Non-prompt PES with the key and no merging: pass 1 stays final, without `WellExtension`, and a warning goes to stdout, so to `logs/<name>_<a>.stdout` only. It must stay off stderr: a non-empty array `.err` marks the job FAILED and deletes its outputs (`q_sys.py::_pickup_kin`).

**Measured, C4H7 hot PES, plain inputs against the KiMecO path, 10 channels, `C4H71-3 <-> C4H71-4` aside.** Caps 48.7, 35.2 at 0.03 atm; 53.4, 44.0 at 1 atm; 68.0, 53.1 at 100 atm. k ratio: no cap 0.80-77; computed caps at the lowest pressure 0.92-3.7, the rest above 2000 K. `tests/unit/data/well_extension_caps/` is a small PES whose caps are 14.20, 19.10 and none at 0.01, 1 and 100 bar, so a wrong reference pressure changes the result.

**Why:** the first pass decides everything, and an empty cap looks like a healthy run. **How to apply:** after a two-pass run read the final input for `WellExtensionCap`; a PES with a cap has a well that really vanished in pass 1.

Sources: the paths above; `tests/unit/test_automech_two_pass_ci.py`. Related: [[mess-global-keys-and-mess-io]], [[kin-units-and-row-ids]].
