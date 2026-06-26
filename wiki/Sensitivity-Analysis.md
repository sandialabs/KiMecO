# 2) Sensitivity Analysis

This section controls both static sensitivity-based parameter selection and on-the-fly periodic sensitivity analysis during optimization.

| Keyword | Default value | Description |
|---|---|---|
| sensi_d | 0.1 | Derivative step multiplier applied to parameter uncertainty in sensitivity analysis. |
| cumul_sensi | 0.95 | Cumulative sensitivity threshold (0 to 1) used to select active parameters. |
| active_p | [] | Explicit list of parameters to perturb. If set, it bypasses sensitivity-based selection. |
| SA_start | 1 | Generation index to start on-the-fly sensitivity analysis. |
| SA_end | 80 | Generation index to stop on-the-fly sensitivity analysis. |
| SA_freq | 20 | Frequency (in generations) for running on-the-fly sensitivity updates. |
