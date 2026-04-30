from datetime import datetime
from typing import Any
import getpass
import random
import string
from logging import INFO
from kimeco.enums import Distrib
from kimeco.enums import Ptype
from kimeco.enums import FreqMode
from kimeco.enums import RestartType


mandatory_keys: dict[str, Any] = {
    # MESS input file containing the nominal parameters
    "mess_inputs": [],
    # path to Cantera mechanism file
    "ct_yaml": "",
    # List of experiments. Each item must define temperature, pressure,
    # composition, simulation template, scoring function and CSV files.
    "experiments": []
                                  }

now: str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
characters = string.ascii_letters + string.digits
rng_name: str = ''.join(random.choice(characters) for _ in range(5))
default_settings: dict[str, Any] = {
    # Location of where the simulation will run
    "scratch_base": f"/scratch/{getpass.getuser()}/kmo/{now}_{rng_name}/",
    # Name of the workdir folder
    "project_name": "KMO_Project",
    # Level of printing in the debugger
    "log_level": INFO,
    # Type of optimizers
    "optimizer": "ga",
    # Parameter for nelder-mead optimizer
    "nm_fatol": 1,
    # Parameter for nelder-mead optimizer
    "nm_xatol": 5e-1,
    # Parameter for nelder-mead optimizer
    "nm_maxiter": 0,
    # Parameter for nelder-mead optimizer
    "nm_maxfev": 0,
    # Parameter for nelder-mead optimizer
    "nm_adaptive": False,
    # Parameter for final nelder-mead optimizer
    "nm_final_fatol": 5e-2,
    # Parameter for final nelder-mead optimizer
    "nm_final_xatol": 5e-3,
    # Parameter for final nelder-mead optimizer
    "nm_final_maxiter": 0,
    # Parameter for final nelder-mead optimizer
    "nm_final_maxfev": 0,
    # Parameter for final nelder-mead optimizer
    "nm_final_adaptive": False,
    # Multiplicating factor for the derivative step used
    # to create the initial simplex in NM
    "nm_dstep": 0.5,
    # Type of genetic algorythm to use
    "ga_type": "tournament",
    # Length of the GOAT list
    "goat_length": 250,
    # Software to use for the master equation code
    "rc_software": "mess",
    # List of temperatures in Kelvin
    "rc_temp": [],
    # List of pressures in Torr
    "rc_pres": [],
    # List of temperatures in Kelvin
    "pp_temp": [],
    # List of pressures in Torr
    "pp_pres": [],
    # Postprocessing initial molar fractions.
    # Same format as initial_X, one entry per pp P/T condition.
    "pp_initial_X": [],
    # List of times for postprocessing simulations.
    # One list per pp P/T condition, ordered like pp_pres/pp_temp.
    "pp_times": [[]],
    # Species to save during postprocessing simulations.
    "pp_species": [],
    # List of ensembles for postprocessing
    "pp_ensembles": ["G0001", "GT-1"],
    # User input unit of pressure
    "pres_unit": 'torr',
    # Scoring function for optimization
    "scoring_func": "weighteddif",
    # Allow species present in MESS but absent from mechanism file.
    # If False, run stops when a missing species is encountered.
    "force_new_molecules": False,
    # CPU used per master equation job
    "cpu_kin": 1,
    # Memory (Mb) used per master equation job
    "mem_kin": 1000,
    # CPU used per simulation job
    "cpu_sim": 1,
    # Memory (Mb) used per simulation job
    "mem_sim": 1000,
    # Maximum number of memory (Mb) used per generation
    "max_mem": 1000000,
    # Default start for NMS
    'NMS_start': '',
    # Maximum number of cpu used per generation
    "max_cpu": 2000,
    # Maximum number of jobs submitted per generation
    "max_jobs": 600,
    # Maximum number of jobs for the user
    "max_user_jobs": 1500,
    # Nodes to exclude from the SLURM submission list
    "exclude_nodes": "",
    # Username for the server hosting the db
    "db_user": getpass.getuser(),
    # IP address of the database host.
    "db_host": "127.0.0.1",
    # Type of perturbator
    "pert": 'normal',
    # Boundary condition for maximal deviation
    "max_std": 4,
    # Standard deviation of energy (kcal/mol) perturbation for wells
    # and bimolecular species
    # Ref for barriers:
    # https://pubs.rsc.org/it-it/content/articlehtml/2025/cp/d5cp01181g
    f"std_{Ptype.WE.value}": 1.0,
    # Standard deviation of energy (kcal/mol) perturbation for barriers
    f"std_{Ptype.BE.value}": 1.5,
    # Mode for frequency perturbation/saving
    "freq_mode": f"{FreqMode.BATCH.value}",
    # Item specific standard deviations
    "specific_std": {},
    # Standard deviation percentage perturbation for wells
    # and bimolecular individual vibrations
    f"std_{Ptype.IFC.value}": 1.1,
    # Standard deviation percentage for batch perturbation of wells
    # and bimolecular vibrations
    f"std_{Ptype.BFC.value}": 1.05,
    # Standard deviation percentage perturbation for hindered rotors
    f"std_{Ptype.HRS.value}": 0.1,
    # Standard deviation multiplicative perturbation for imaginary frequencies
    f"std_{Ptype.IF.value}": 1.1,
    # Energy transfer probability, factor, percentage
    f"std_{Ptype.ETF.value}": 0.25,
    # Energy transfer probability, exponent, absolute
    f"std_{Ptype.ETP.value}": 0.075,
    # Lennard Jones, epsilon, percentage
    f"std_{Ptype.EPSI.value}": 0.1,
    # Lennard Jones, sigma, percentage
    f"std_{Ptype.SIG.value}": 0.1,
    # Multiplicating/dividing factor for sym  factor of bl reactions
    f"std_{Ptype.SFC.value}": 2.0,
    # Multiplicating/dividing factor for sym factor of M-D rotors
    f"std_{Ptype.MRC.value}": 1.5,
    # RNG distribution of energy (kcal/mol) perturbation for wells
    # and bimolecular species
    f"distrib_{Ptype.WE.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution of energy (kcal/mol) perturbation for barriers
    f"distrib_{Ptype.BE.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for wells
    # and bimolecular individual vibrations
    f"distrib_{Ptype.IFC.value}": f"{Distrib.LOGNORMAL.value}",
    # RNG distribution for wells
    # and bimolecular batch vibrations
    f"distrib_{Ptype.BFC.value}": f"{Distrib.LOGNORMAL.value}",
    # RNG distribution for hindered rotors
    f"distrib_{Ptype.HRS.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for imaginary frequencies
    f"distrib_{Ptype.IF.value}": f"{Distrib.LOGNORMAL.value}",
    # RNG distribution for energy transfer probability, factor
    f"distrib_{Ptype.ETF.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for energy transfer probability, exponent
    f"distrib_{Ptype.ETP.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for Lennard Jones, epsilon
    f"distrib_{Ptype.EPSI.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution Lennard Jones, sigma
    f"distrib_{Ptype.SIG.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for symmetry factor of bl reactions
    f"distrib_{Ptype.SFC.value}": f"{Distrib.LOGNORMAL.value}",
    # RNG distribution for symmetry factor of multi-d rotors
    f"distrib_{Ptype.MRC.value}": f"{Distrib.LOGNORMAL.value}",
    # Convergence threshold for well energies
    f"conv_{Ptype.WE.value}": 0.1,
    # Convergence threshold for barriers energies
    f"conv_{Ptype.BE.value}": 0.1,
    # Convergence threshold for energy transfer probability, exponent
    f"conv_{Ptype.ETP.value}": 0.01,
    # Weights of the species in the scoring function
    # Type should be dict[str, float]
    # It is normalized so that the sum of the weights = number of species
    "w_species": {},
    # Restart modes, and treatment of existing tables/db
    "restart": RestartType.DEFAULT.value,
    # Number of models per generation
    "n_mdl": 500,
    # Value of score above which a generation won't converge
    "max_score": 4.0,
    # Average value of best models' score for convergence
    "score_conv": 2,
    # Maximum number of generations
    "max_gen": 10,
    # Percentage of deviation of means and stds of parameters to converge
    "param_conv": 0.01,
    # Multiplicating factors of std parameters for derivative in
    # sensitivity analysis
    "sensi_d": 0.1,
    # Threshold of cumulative sensitivity percent to select
    # important parameters to perturb
    "cumul_sensi": 0.95,
    # User given list of parameters to perturb. All if empty.
    "active_p": [],
    # Frequency of the sensitivity analysis
    "SA_freq": 20,
    # From which generation to start the sensitivity analysis
    "SA_start": 1,
    # From which generation to end the sensitivity analysis
    "SA_end": 80,
    # Key: generation number.
    # Value: list of parameters added at that generation
    "SA_restart": {},
    # Number of threads in the main process for I/O operations
    "threads": 1
}
