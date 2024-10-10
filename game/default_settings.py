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
    # CSV files for the experimental reaction profiles
    # list of str correspondint to the path of the profiles
    # order is P1T1, P1T2, ..., P2T1, P2T2,...
    "exp_profiles": []
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
    "mem_kin": 10000,
    # CPU used per simulation job
    "cpu_sim": 1,
    # Memory (Mb) used per simulation job
    "mem_sim": 500,
    # Maximum number of memory (Mb) used per generation
    "max_mem": 1000000,
    # Maximum number of cpu used per generation
    "max_cpu": 1000,
    # Maximum number of jobs submitted per generation
    "max_jobs": 2000,
    # Username for the server hosting the db
    "db_user": getpass.getuser(),
    # IP address of the database host. Should have a postgreSQL server
    "db_host": "127.0.0.1",
    # Absolute value of energy (kcal/mol) perturbation for wells
    # and bimolecular species
    "pert_e": 1.0,
    # Absolute value of energy (kcal/mol) perturbation for barriers
    "pert_b": 1.0,
    # Absolute percentage perturbation for wells
    # and bimolecular vibrations
    "pert_f": 0.05,
    # Absolute percentage perturbation for hindered rotors
    "pert_hr": 0.2,
    # Absolute percentage perturbation for imaginary frequencies
    "pert_if": 0.2,
    # Energy transfer probability, factor, percentage
    "pert_etf": 0.5,
    # Energy transfer probability, exponent, percentage
    "pert_ete": 0.15,
    # Lennard Jones, epsilon, percentage
    "pert_epsi": 0.2,
    # Lennard Jones, sigma, percentage
    "pert_sigma": 0.2,
    # Multiplicating/dividing factor for barrierless reactions
    "pert_sf": 2.0,
    # Name of the scoring function class to use
    "scoring_func": "basic",
    # list of weights for specific PT.
    # Order is P1T1, P1T2, ..., P2T1, P2T2,...
    "w_exp": [],
    # Weights of the species in the scoring function
    # Type should be dict[str, float]
    # It is normalized so that the sum of the weights = number of species
    "w_species": {}
}
