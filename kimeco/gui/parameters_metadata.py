"""
Parameter metadata extraction and organization for kmo_start GUI.

This module extracts parameter information from default_settings.py and
organizes them by category for easy display in the GUI.
"""

from typing import Any, Dict, List
from kimeco.default_settings import default_settings, mandatory_keys


class ParameterMetadata:
    """Container for parameter information from default_settings."""

    def __init__(
        self,
        name: str,
        default: Any,
        description: str = "",
        category: str = ""
    ):
        self.name = name
        self.default = default
        self.description = description
        self.category = category
        self.param_type = self._infer_type(default)

    def _infer_type(self, value: Any) -> str:
        """Infer parameter type from default value."""
        if isinstance(value, bool):
            return "bool"
        elif isinstance(value, int):
            return "int"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, list):
            return "list"
        elif isinstance(value, dict):
            return "dict"
        else:
            return "str"


# Parameter descriptions extracted from default_settings.py comments
PARAMETER_DESCRIPTIONS = {
    "scratch_base": "Location for simulation runs",
    "project_name": "Name of the workdir folder",
    "log_level": "Level of logging output",
    "optimizer": "Type of optimizer (ga or nelder-mead)",
    "ga_type": "Type of GA (tournament or exponential)",
    "goat_length": "Length of GOAT list",
    "nm_fatol": "NM function absolute tolerance",
    "nm_xatol": "NM parameter absolute tolerance",
    "nm_maxiter": "NM maximum iterations",
    "nm_maxfev": "NM maximum function evaluations",
    "nm_adaptive": "Enable adaptive NM algorithm",
    "nm_dstep": "Derivative step for initial simplex",
    "NMS_start": "Default start for NM simplex",
    "rc_software": "Master equation software",
    "rc_temp": "Temperatures (K) for rate coefficients",
    "rc_pres": "Pressures (Torr) for rate coefficients",
    "pp_temp": "Temperatures (K) for postprocessing",
    "pp_pres": "Pressures (Torr) for postprocessing",
    "pp_initial_X": "Initial molar fractions for PP",
    "pp_times": "Times for postprocessing simulations",
    "pp_species": "Species to save in postprocessing",
    "pp_ensembles": "Ensembles for postprocessing",
    "pres_unit": "Pressure unit",
    "force_new_molecules": "Allow missing species in mechanism",
    "cpu_kin": "CPU per master equation job",
    "mem_kin": "Memory (MB) per master equation job",
    "cpu_sim": "CPU per simulation job",
    "mem_sim": "Memory (MB) per simulation job",
    "max_mem": "Max memory (MB) per generation",
    "max_cpu": "Max CPU per generation",
    "max_jobs": "Max jobs per generation",
    "max_user_jobs": "Max jobs for user",
    "exclude_nodes": "SLURM nodes to exclude",
    "db_user": "Database username",
    "db_host": "Database host IP",
    "pert": "Type of perturbator",
    "max_std": "Boundary for max deviation",
    "freq_mode": "Frequency perturbation mode",
    "std_we": "Std dev for well energy",
    "std_be": "Std dev for barrier energy",
    "std_freq": "Std dev for frequencies",
    "std_bfc": "Std dev for batch frequencies",
    "std_hrs": "Std dev for hindered rotors",
    "std_if": "Std dev for imaginary frequency",
    "std_fact": "Std dev for energy transfer factor",
    "std_pow": "Std dev for energy transfer power",
    "std_epsilon": "Std dev for Lennard-Jones epsilon",
    "std_sigma": "Std dev for Lennard-Jones sigma",
    "std_sfc": "Std dev for symmetry factor",
    "std_mrc": "Std dev for multi-D rotor",
    "distrib_we": "Distribution for well energy",
    "distrib_be": "Distribution for barrier energy",
    "distrib_freq": "Distribution for frequencies",
    "distrib_bfc": "Distribution for batch frequencies",
    "distrib_hrs": "Distribution for hindered rotors",
    "distrib_if": "Distribution for imaginary frequency",
    "distrib_fact": "Distribution for energy transfer factor",
    "distrib_pow": "Distribution for energy transfer power",
    "distrib_epsilon": "Distribution for Lennard-Jones epsilon",
    "distrib_sigma": "Distribution for Lennard-Jones sigma",
    "distrib_sfc": "Distribution for symmetry factor",
    "distrib_mrc": "Distribution for multi-D rotor",
    "conv_we": "Convergence threshold for well energy",
    "conv_be": "Convergence threshold for barrier",
    "conv_pow": "Convergence threshold for power",
    "w_species": "Weights of species in scoring",
    "restart": "Restart mode",
    "n_mdl": "Number of models per generation",
    "max_score": "Max score for non-convergence",
    "score_conv": "Score convergence threshold",
    "max_gen": "Maximum generations",
    "param_conv": "Parameter convergence threshold",
    "sensi_d": "Sensitivity derivative multiplier",
    "cumul_sensi": "Cumulative sensitivity threshold",
    "active_p": "Parameters to perturb",
    "SA_freq": "Sensitivity analysis frequency",
    "SA_start": "Start generation for SA",
    "SA_restart": "SA restart dictionary",
    "threads": "Number of I/O threads",
}

# Parameter categories for GUI organization
PARAMETER_CATEGORIES = {
    "scratch_base": "Workdir & System",
    "project_name": "Workdir & System",
    "log_level": "Workdir & System",
    "threads": "Workdir & System",
    "optimizer": "Optimizer",
    "ga_type": "Optimizer",
    "goat_length": "Optimizer",
    "nm_fatol": "Nelder-Mead",
    "nm_xatol": "Nelder-Mead",
    "nm_maxiter": "Nelder-Mead",
    "nm_maxfev": "Nelder-Mead",
    "nm_adaptive": "Nelder-Mead",
    "nm_dstep": "Nelder-Mead",
    "NMS_start": "Nelder-Mead",
    "rc_software": "Rate Coefficients",
    "rc_temp": "Rate Coefficients",
    "rc_pres": "Rate Coefficients",
    "pres_unit": "Rate Coefficients",
    "pp_temp": "Postprocessing",
    "pp_pres": "Postprocessing",
    "pp_initial_X": "Postprocessing",
    "pp_times": "Postprocessing",
    "pp_species": "Postprocessing",
    "pp_ensembles": "Postprocessing",
    "std_we": "Perturbation",
    "std_be": "Perturbation",
    "std_freq": "Perturbation",
    "std_bfc": "Perturbation",
    "std_hrs": "Perturbation",
    "std_if": "Perturbation",
    "std_fact": "Perturbation",
    "std_pow": "Perturbation",
    "std_epsilon": "Perturbation",
    "std_sigma": "Perturbation",
    "std_sfc": "Perturbation",
    "std_mrc": "Perturbation",
    "distrib_we": "Perturbation",
    "distrib_be": "Perturbation",
    "distrib_freq": "Perturbation",
    "distrib_bfc": "Perturbation",
    "distrib_hrs": "Perturbation",
    "distrib_if": "Perturbation",
    "distrib_fact": "Perturbation",
    "distrib_pow": "Perturbation",
    "distrib_epsilon": "Perturbation",
    "distrib_sigma": "Perturbation",
    "distrib_sfc": "Perturbation",
    "distrib_mrc": "Perturbation",
    "pert": "Perturbation",
    "max_std": "Perturbation",
    "freq_mode": "Perturbation",
    "conv_we": "Convergence",
    "conv_be": "Convergence",
    "conv_pow": "Convergence",
    "score_conv": "Convergence",
    "param_conv": "Convergence",
    "restart": "Optimization Control",
    "n_mdl": "Optimization Control",
    "max_score": "Optimization Control",
    "max_gen": "Optimization Control",
    "w_species": "Scoring",
    "force_new_molecules": "Mechanism",
    "cpu_kin": "Resources",
    "mem_kin": "Resources",
    "cpu_sim": "Resources",
    "mem_sim": "Resources",
    "max_mem": "Resources",
    "max_cpu": "Resources",
    "max_jobs": "Resources",
    "max_user_jobs": "Resources",
    "exclude_nodes": "Resources",
    "db_user": "Database",
    "db_host": "Database",
    "sensi_d": "Sensitivity Analysis",
    "cumul_sensi": "Sensitivity Analysis",
    "active_p": "Sensitivity Analysis",
    "SA_freq": "Sensitivity Analysis",
    "SA_start": "Sensitivity Analysis",
    "SA_restart": "Sensitivity Analysis",
}


def get_parameter_metadata(param_name: str) -> ParameterMetadata:
    """Get metadata for a single parameter."""
    if param_name in default_settings:
        default_value = default_settings[param_name]
    else:
        default_value = None

    description = PARAMETER_DESCRIPTIONS.get(param_name, "")
    category = PARAMETER_CATEGORIES.get(param_name, "Other")

    return ParameterMetadata(
        name=param_name,
        default=default_value,
        description=description,
        category=category
    )


def get_all_parameters_by_category() -> Dict[str, List[ParameterMetadata]]:
    """Organize all parameters by category."""
    params_by_category: Dict[str, List[ParameterMetadata]] = {}

    for param_name in default_settings:
        metadata = get_parameter_metadata(param_name)
        category = metadata.category

        if category not in params_by_category:
            params_by_category[category] = []

        params_by_category[category].append(metadata)

    # Sort parameters within each category by name
    for category in params_by_category:
        params_by_category[category].sort(key=lambda x: x.name)

    return params_by_category


def get_mandatory_parameters() -> Dict[str, Any]:
    """Get mandatory parameters that must be provided."""
    return mandatory_keys.copy()
