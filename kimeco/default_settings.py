from typing import Any
import getpass
from kimeco.enums import Distrib
from kimeco.enums import Ptype
from kimeco.enums import FreqMode


mandatory_keys: dict[str, Any] = {
    # MESS input file containing the nominal parameters
    "initial_mess": "",
    # path to Cantera mechanism file
    "ct_yaml": "",
    # Dictionary {'ct_name': float} of initial density (molecules/cm^3).
    # (converted to molar fraction in Cantera)
    # Note: One specie concentration can be 'base', meaning 1-the rest.
    # If no 'base' specie is given, N2 is assumed to be the base.
    # (most likely with air composition).
    "initial_C": {},
    # CSV files for the experimental reaction profiles.
    # list of str corresponding to the path of the profiles
    # order is P1T1, P1T2, ..., P2T1, P2T2,...
    "exp_profiles": [],
    # CSV files for the experimental error associated with
    # the reaction profiles.
    # list of str corresponding to the path of the profiles
    # order is eP1T1, eP1T2, ..., eP2T1, eP2T2,...
    "exp_errors": []
                                  }

default_settings: dict[str, Any] = {
    "project_name": "KMO_Project",
    # Software to use for the master equation code
    "rc_software": "mess",
    # List of temperatures in Kelvin
    "rc_temp": [],
    # List of pressures in Torr
    "rc_pres": [],
    # User input unit of pressure
    "pres_unit": 'torr',
    # Keys: name of species in the initial mess file
    # Values: name of the species in the mechanism file
    "ct_names": {},
    # CPU used per master equation job
    "cpu_kin": 1,
    # Memory (Mb) used per master equation job
    "mem_kin": 1000,
    # CPU used per simulation job
    "cpu_sim": 1,
    # Memory (Mb) used per simulation job
    "mem_sim": 1000,
    # Memory (Mb) used per simulation job
    "mem_hlp": 500,
    # Maximum number of memory (Mb) used per generation
    "max_mem": 1000000,
    # Maximum number of cpu used per generation
    "max_cpu": 2000,
    # Maximum number of jobs submitted per generation
    "max_jobs": 600,
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
    f"std_{Ptype.WE.value}": 0.5,
    # Standard deviation of energy (kcal/mol) perturbation for barriers
    f"std_{Ptype.BE.value}": 0.5,
    # Mode for frequency perturbation/saving
    "freq_mode": f"{FreqMode.BATCH.value}",
    # Standard deviation percentage perturbation for wells
    # and bimolecular individual vibrations
    f"std_{Ptype.IFC.value}": 0.05,
    # Standard deviation percentage for batch perturbation of wells
    # and bimolecular vibrations
    f"std_{Ptype.BFC.value}": 0.1,
    # Standard deviation percentage perturbation for hindered rotors
    f"std_{Ptype.HRS.value}": 0.1,
    # Standard deviation percentage perturbation for imaginary frequencies
    f"std_{Ptype.IF.value}": 0.1,
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
    f"std_{Ptype.MRC.value}": 2.0,
    # RNG distribution of energy (kcal/mol) perturbation for wells
    # and bimolecular species
    f"distrib_{Ptype.WE.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution of energy (kcal/mol) perturbation for barriers
    f"distrib_{Ptype.BE.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for wells
    # and bimolecular individual vibrations
    f"distrib_{Ptype.IFC.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for wells
    # and bimolecular batch vibrations
    f"distrib_{Ptype.BFC.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for hindered rotors
    f"distrib_{Ptype.HRS.value}": f"{Distrib.NORMAL.value}",
    # RNG distribution for imaginary frequencies
    f"distrib_{Ptype.IF.value}": f"{Distrib.NORMAL.value}",
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
    # Name of the scoring function class to use
    "scoring_func": "weighteddif",
    # Name of species as in exp profiles header
    # Selected species for scoring
    'score_sp': [],
    # Name of species as in exp profiles header
    # Exclude species for scoring
    'exclude_sp': [],
    # list of weights for specific PT.
    # Order is P1T1, P1T2, ..., P2T1, P2T2,...
    "w_exp": [],
    # Weights of the species in the scoring function
    # Type should be dict[str, float]
    # It is normalized so that the sum of the weights = number of species
    "w_species": {},
    # Restart modes, and treatment of existing tables/db
    "restart": 'default',
    # Number of elements per generation
    "n_elem": 500,
    # Value of score under which a generation has converged
    "score_conv": 0.01,
    # Maximum number of generations
    "max_gen": 10,
    # Percentage of deviation of means and stds of parameters to converge
    "final_conv": 0.01,
    # Numbers of helpers to save the simulations profiles
    "max_helpers": 10,
    # Multiplicating factors of std parameters for derivative in
    # sensitivity analysis
    "sensi_d": 0.1,
    # Threshold of cumulative sensitivity percent to select
    # important parameters to perturb
    "cumul_sensi": 0.95,
    # User given list of parameters to perturb. All if empty.
    "only_perturb": [],
    # Frequency of the sensitivity analysis
    "SA_freq": 1000,
    # From which generation to start the sensitivity analysis
    "SA_start": 1,
    # Number of thread in the main process for I/O operations
    "thread": 5
}
