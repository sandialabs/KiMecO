---
name: prompt-paper-reference
description: "The C4H8 prompt system's source paper (Pratali Maffei et al., CNF 2023) and where to read its full text"
metadata:
  node_type: memory
  type: reference
  originSessionId: cb7d02e6-bd70-45fe-beb6-84d0c0475394
  modified: 2026-10-01T20:32:07.155Z
---

Paper: L. Pratali Maffei et al., "Automated identification and calculation of prompt effects in kinetic mechanisms using statistical models", Combust. Flame (2023), ScienceDirect pii S0010218022004394.
ScienceDirect returns 403 to WebFetch; the accepted manuscript is open at https://www.osti.gov/servlets/purl/2474892 (PDF → `pdftotext -layout`).

Figures 1-7 of that PDF are vector graphics: `pdftocairo -svg` gives each curve as a spline whose on-curve nodes are the plotted values, even where a curve is clipped by the axes (Figure 5: 67 path points = 23 temperatures of the MESS grid; Figure 6: 46 = 16). So the plotted numbers can be compared one to one, without digitising by eye.

The method (BF calculation, models, equation → code map, how k = BF·k1 is built) is summarised in [[prompt-branching-fractions]]. System map: [[c4h8-prompt-system-map]].
