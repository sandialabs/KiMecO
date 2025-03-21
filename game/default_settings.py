from typing import Any
import getpass


mandatory_keys: dict[str, Any] = {
    # MESS input file containing the nominal parameters
    "initial_mess": "",
    # path to Cantera mechanism file
    "ct_yaml": "",
    # Dictionary {'ct_name': float} of initial molecular percentage.
    # (see X in Cantera)
    # Note: One specie concentration can be 'base', meaning 1-the rest.
    # If no 'base' specie is given, N2 is assumed to be the base.
    # (most likely with air composition).
    "initial_X": {},
    # CSV files for the experimental reaction profiles.
    # list of str corresponding to the path of the profiles
    # order is P1T1, P1T2, ..., P2T1, P2T2,...
    "exp_profiles": [],
    # CSV files for the experimental error associated with
    # the reaction profiles.
    # list of str corresponding to the path of the profiles
    # order is eP1T1, eP1T2, ..., eP2T1, eP2T2,...
    "exp_error": []
                                  }

default_settings: dict[str, Any] = {
    "project_name": "gameProject",
    # Software to use for the master equation code
    "rc_software": "mess",
    # List of temperatures in Kelvin
    "rc_temp": [],
    # List of pressures in Torr
    "rc_pres": [],
    # Keys: name of species in the initial mess file
    # Values: name of the species in the mechanism file
    "ct_names": {},
    # Time of a simulation in seconds
    "sim_time": 0.1,
    # Timestep length during the simulation
    "sim_tstep": 0.0001,
    # CPU used per master equation job
    "cpu_kin": 4,
    # Memory (Mb) used per master equation job
    "mem_kin": 1500,
    # CPU used per simulation job
    "cpu_sim": 1,
    # Memory (Mb) used per simulation job
    "mem_sim": 100,
    # Maximum number of memory (Mb) used per generation
    "max_mem": 1000000,
    # Maximum number of cpu used per generation
    "max_cpu": 2000,
    # Maximum number of jobs submitted per generation
    "max_jobs": 2000,
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
    "std_e": 1.0,
    # Standard deviation of energy (kcal/mol) perturbation for barriers
    "std_b": 1.0,
    # Standard deviation percentage perturbation for wells
    # and bimolecular vibrations
    "std_hf_p": 0.05,
    # Standard deviation percentage perturbation for wells
    # and bimolecular vibrations
    "std_lf_p": 0.2,
    # Standard deviation percentage perturbation for hindered rotors
    "std_hr": 0.2,
    # Standard deviation percentage perturbation for imaginary frequencies
    "std_if": 0.2,
    # Energy transfer probability, factor, percentage
    "std_fact": 0.5,
    # Energy transfer probability, exponent, absolute
    "std_pow": 0.15,
    # Lennard Jones, epsilon, percentage
    "std_epsi": 0.2,
    # Lennard Jones, sigma, percentage
    "std_sigma": 0.2,
    # Multiplicating/dividing factor for barrierless reactions
    "std_sf": 2.0,
    # Name of the scoring function class to use
    "scoring_func": "weighteddif",
    # Absolute error for all species for all experiments
    "abs_err": 1e-9,
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
    "only_perturb": []
}
