from typing import Any


mandatory_keys: dict[str, str] = {"initial_mess": "",
                                  "ct_yaml": ""
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
    "pert_sf": 2.0
}
