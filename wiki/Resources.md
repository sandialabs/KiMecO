# 6) Resources

This section controls per-job SLURM resources and global scheduling limits.

| Keyword | Default value | Description |
|---|---|---|
| cpu_kin | 1 | CPUs requested per master-equation job. |
| mem_kin | 1000 | Memory (MB) per master-equation job. |
| cpu_sim | 1 | CPUs requested per simulation job. |
| mem_sim | 1000 | Memory (MB) per simulation job. |
| max_cpu | 2000 | Global CPU budget per generation/submission cycle. |
| max_mem | 1000000 | Global memory budget (MB) per generation/submission cycle. |
| max_jobs | 600 | Maximum submitted jobs for current KiMecO instance. |
| max_user_jobs | 1500 | Maximum submitted jobs for the current user. |
| exclude_nodes | "" | Comma-separated SLURM nodes to exclude. |
