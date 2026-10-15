---
name: pesviewer-c4h8-inputs
description: "PESViewer inputs for the 12 C4H8 prompt MESS inputs live in non_thermal/PESVIEWER; pesviewer quirks (single-TS crash, save arg ignored, TkAgg)"
metadata:
  node_type: memory
  type: project
  originSessionId: 45d7d73a-b3f7-45c0-8112-ca5ee3621ebb
  modified: 2026-10-01T20:38:32.618Z
---

Created 2026-10-01: `/data/home/csoulie/non_thermal/PESVIEWER/<name>/<name>.inp` + `<name>/xyz/`, one per MESS input of [[c4h8-prompt-system-map]] (C4H7 PES is named `wellcap_eigmax02`, the folder holding its mess.inp). Regenerate with `PESVIEWER/mess2pesviewer.py`. Bimolecular = fragments joined by `_`, xyz `<bimol>1.xyz`/`<bimol>2.xyz` (pesviewer code convention, not the README's `name_index`); fake wells keep MESS names (`FW-`/`FakeW-`, contain `+`).

PESViewer quirks (pv env, `~/.conda/envs/pv`, v1.1.0):
- `create_interactive_graph` divides by (max−min) TS energy → ZeroDivisionError when a PES has a single TS. **How to apply:** keep fake PST barriers (FRB/FPB, FakeRB/FakePB) as `<ts>` entries, not `<barrierless>`.
- `pesviewer file.inp save` is ignored (read_input resets `save`); use `save 1` in the input instead.
- Hardcodes `matplotlib.use('TkAgg')`; headless runs need it monkeypatched to Agg.
