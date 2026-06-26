# 3) Optimizer

This section selects optimization mode and maps GUI scheme choices to runtime optimizer fields.

## 3.1 Core optimization controls

These keywords control the optimizer type, GA selection strategy, and convergence thresholds.

| Keyword | Default value | Description |
|---|---|---|
| optimizer | "ga" | Type of optimizer. Possible values: "ga" or "nelder-mead". |
| ga_type | "exp" | Genetic algorithm selection strategy. Possible values: "exp" or "tournament". |
| NMS_start | "" | Optional seed generation for NM swarm. For example G0001 is the first generation ran by a GA (which only correspond to models perturbed from the initial model). GT-1 point to the last (pythonic -1) GOAT ensemble, which is the ensemble of top models from all previously ran generation. |
| n_mdl | 500 | Number of models per generation. |
| goat_length | 250 | Size of top models kept in the GOAT ensemble. |
| max_gen | 10 | Maximum generations. Note: use 1 if you only want to perform a "Swarm of Nelder-Mead".|

## 3.2 Nelder-Mead controls

These keywords control Nelder-Mead behavior. They are only used if optimizer is set to "nelder-mead". See SciPy documentation for details on the Nelder-Mead algorithm and its parameters (https://docs.scipy.org/doc/scipy/reference/optimize.minimize-neldermead.html).

| Keyword | Default value | Description |
|---|---|---|
| nm_fatol | 1 | NM function absolute tolerance. |
| nm_xatol | 0.5 | NM parameter absolute tolerance. |
| nm_maxiter | 0 | NM max iterations (0 means solver default behavior where applicable). |
| nm_maxfev | 0 | NM max function evaluations (0 means solver default behavior where applicable). |
| nm_dstep | 0.5 | Initial simplex scaling step for NM. The simplex is created using a derivative step of every active parameters, plus the initial model. |
| nm_adaptive | false | Enables adaptive Nelder-Mead variant. |

During the final stage of optimization, the Nelder-Mead algorithm is run again with tighter tolerances after a second sensitivity analysis from the previously optimized simplex. These keywords control the final-stage NM behavior. They are only used if optimizer is set to "nelder-mead". See SciPy documentation for details on the Nelder-Mead algorithm and its parameters (https://docs.scipy.org/doc/scipy/reference/optimize.minimize-neldermead.html).

| Keyword | Default value | Description |
|---|---|---|
| nm_final_fatol | 0.05 | Final-stage NM tolerance (in defaults, currently not surfaced in GUI controls). |
| nm_final_xatol | 0.005 | Final-stage NM parameter tolerance (not surfaced in GUI controls). |
| nm_final_maxiter | 0 | Final-stage NM max iterations (not surfaced in GUI controls). |
| nm_final_maxfev | 0 | Final-stage NM max evaluations (not surfaced in GUI controls). |
| nm_final_adaptive | false | Final-stage adaptive flag (not surfaced in GUI controls). |
