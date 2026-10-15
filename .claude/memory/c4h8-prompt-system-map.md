---
name: c4h8-prompt-system-map
description: "The C4H8 prompt-dissociation system is 13 MESS inputs (5 PESs, 4 prompt groups); where each lives and which one is missing"
metadata:
  node_type: memory
  type: project
  originSessionId: b01a3fe0-4770-4cd7-9363-431029af30cf
  modified: 2026-10-01T19:20:09.019Z
---

C4H8 prompt system (identified 2026-10-01) = 12 abstraction MESS inputs + 1 C4H7 hot PES, defined by `/data/home/csoulie/non_thermal/AUTOMECH_INPUT/` (mechanism.dat, pes_groups.dat, run.dat).

- PES 1 C4H7 (hot): `amech-dev/C4H8-prompt/C4H7_JC/wellcap_eigmax02` — this variant matches the final `RATE CONSTANTS/base.txt`.
- PES 2 H, PES 4 OH (3 channels each): run folders in `amech-dev/C4H8-prompt/` (= the 7 FLDs in prompt.py, byte-identical to `non_thermal/ME_INPUT/*.inp`).
- PES 3 O: 3:3 `2-O_C4H71-3` run folder exists; 3:1 `O_C4H71-3` input only in ME_INPUT; **3:2 `O_C4H71-4` (C4H8-1+O→C4H71-4+OH) missing from disk**, though its rates are in RATE CONSTANTS.
- PES 5 CH3: `CH3_C4H71-3`, `CH3_C4H71-4`, `2-CH3_C4H71-3` inputs only in ME_INPUT (no outputs).

**Why:** prompt.py FLDs only covers the H and OH groups. **How to apply:** for a full-system prompt run, FLDs needs all 13; run.dat save_prefix is on LCRC (/lcrc/project/PACC/AutoMech/data/save), not this machine. See [[automech-fake-wells-doc]] for the fake-well label eras (FW- vs FakeW-) mixed across these inputs.

Full SOP (system map, run procedure, pitfalls): `/data/home/csoulie/non_thermal/non-thermal-sop.md`. Verified 2026-10-01: prompt.py with current FLDs in the `automech` env takes ~7 min and reproduces the existing rates within 0.7 % but adds 10 spurious `FW-` reactions (old-era labels leak through the current mess_io filter).
