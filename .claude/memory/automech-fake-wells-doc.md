---
name: automech-fake-wells-doc
description: "Where the thorough write-up of AutoMech fake-well handling (writing, reading, version history, pitfalls) lives"
metadata:
  node_type: memory
  type: reference
  originSessionId: b01a3fe0-4770-4cd7-9363-431029af30cf
  modified: 2026-10-01T18:46:18.759Z
---

Thorough doc on how AutoMech builds and post-processes MESS fake wells (FakeW-/FW-/F<n> labels, PST fake barriers, 1→3 kcal/mol depth change, dummy-frequency rules, mess_io filter/merge of rate constants, PED energy zero, version timeline with commits): `/home/csoulie/non_thermal/amech-dev/C4H8-prompt/FakeWell_in_automech.md` (written 2026-10-01).

AutoMech source checkout with full git history: `/data/home/csoulie/automech/{mechdriver,autoio,autochem,mechanalyzer}`. Use the `automech` conda env (`~/.conda/envs/automech`, from `conda env list`, not under miniconda3/envs): it has `mess`, mechanalyzer, mess_io from the local checkout. `kimeco` lacks mechanalyzer.

Key non-obvious facts: detection is name-based only; old `FW-` labels leak through the current `'Fake'` filter; PED zero is the bimolecular GroundEnergy, not the fake well.
