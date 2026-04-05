import csv
import os
import sys
import json
from typing import Any
from kimeco.default_settings import default_settings, mandatory_keys
import numpy as np
from numpy import float64
from numpy.typing import NDArray
from scipy.constants import gas_constant
import cantera.with_units as ctu
from kimeco.logger_config import KMOLogger
from kimeco.enums import Distrib, Optimizers, Pclass, Ptype
from kimeco.enums import FreqMode, RestartType


ureg: ctu.UnitRegistry = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')


class KMOInput:
    def __init__(self,
                 input_file: str,
                 init_loc: str,
                 klog: KMOLogger) -> None:
        """Ensemble of different functions to check the
        user's input

        Args:
            input_file (str): path to user input
            klog (KMOLogger): logger
        """
        self.init_loc: str = init_loc + '/'
        self.input_file: str = input_file
        self.klog: KMOLogger = klog
        self.cancel_run: bool = False
        self.json_file: dict[str, Any] = self.load_input()
        self.n_exp: int

    def load_input(self) -> dict:
        # File exist?
        input_path: str = self.init_loc + self.input_file
        if not os.path.isfile(path=input_path):
            self.klog.info(f'The input_file {input_path} was not found.')
            sys.exit(-1)

        # Is JSON file?
        if input_path[-5:].casefold() != '.json':
            self.klog.info(
                "The argument given to KIMECO should be a json file.")
            sys.exit(-1)

        with open(input_path, mode='r') as f:
            return json.load(fp=f)

    def basic_checks(self) -> None:
        # Has mandatory keys?
        for key, value in mandatory_keys.items():
            if key not in self.json_file:
                if key == 'initial_C':
                    if 'initial_X' not in self.json_file:
                        self.klog.info(
                            f"{key} or initial_X is a mandatory keyword.")
                        continue
                    else:
                        # The initial composition was given as a percentage
                        continue
                self.klog.info(f"{key} is a mandatory keyword.")
                self.cancel_run = True
            elif key == 'cantera_tpl':
                if not os.path.isfile(self.init_loc+self.json_file[key]):
                    self.klog.info(
                        f"Cantera tpl file {self.json_file[key]} not found.")
                    self.cancel_run = True
                    continue
                # If file exist try to open it
                try:
                    with open(
                        self.init_loc+self.json_file[key],
                        mode='r') as f:
                        cantera_tpl: str = f.read()
                except Exception as e:
                    self.klog.info(
                        f"Cannot read {self.json_file[key]}.")
                    self.klog.info(str(e))
                    self.cancel_run = True
                    continue
                # if file can be read, check if it contains the keywords
                if not cantera_tpl:
                    raise ValueError("Cantera tpl file is empty.")
                try:
                    _: str = cantera_tpl.format(
                        init_loc='test',
                        input_file='test',
                        scratchdir='test',
                        el_num=0,
                        db='test',
                        tbl_map_by_pes='test',
                        rates_by_pes='test',
                        time='test',
                        all_tsteps='test',
                        gen_name='test',
                        to_watch='test'
                        )
                except KeyError as e:
                    msg: str = f"Keyword {e} not in the Cantera tpl.\n"
                    msg += "It should contain the following keywords:\n"
                    msg += "init_loc, input_file, scratchdir, el_num, db,"
                    msg += " tbl_map, rates, time, all_tsteps,"
                    msg += " gen_name, to_watch"
                    self.klog.info(msg)
                    self.cancel_run = True
                    continue
                self.json_file[key] = cantera_tpl
            elif not isinstance(self.json_file[key], type(value)):
                if isinstance(value, float) and \
                   isinstance(self.json_file[key], int):
                    continue
                self.klog.info(
                    f"{key} has incorrect type. Type should be {type(value)}")
                self.cancel_run = True

        if 'pres_unit' not in self.json_file:
            self.json_file['pres_unit'] = default_settings['pres_unit']
        self.klog.info(
            f"Pressure unit in input assumed in {self.json_file['pres_unit']}")

    def create_initial_conditions(self,
                                  postprocess: bool = False) -> None:
        """Create the initial conditions for every experiments
        """
        if postprocess:
            self.n_exp: int = \
                len(self.json_file['pp_pres'])*len(self.json_file['pp_temp'])
        else:
            self.n_exp: int = \
                len(self.json_file['rc_pres'])*len(self.json_file['rc_temp'])
        base_key = 'n2'

        if 'initial_X' in self.json_file:
            if not isinstance(self.json_file['initial_X'], list)\
               or len(self.json_file['initial_X']) != self.n_exp:
                msg: str = 'initial_X: Should be a list of dictionaries.\n'
                msg += 'Each dict should have for key '
                msg += 'the specie name in the ct mechanism.\n'
                msg += 'The value should be the ratio of that specie.'
                self.klog.info(msg)
                self.cancel_run = True
            else:
                for exp in self.json_file['initial_X']:
                    base_given = False
                    sum = 0.0
                    for k, v in exp.items():
                        if not isinstance(k, str):
                            self.klog.info(
                                'initial_X keys should be ct species names.')
                            self.cancel_run = True
                            break
                        # Set the base
                        if isinstance(v, str) and v.casefold() == 'base':
                            if not base_given:
                                self.klog.info(f"Base specie: {k}.")
                                base_key: str = k
                                base_given = True
                            else:
                                self.klog.info(
                                    "Two base are given for an experiment.")
                                self.cancel_run = True
                        # Check total composition
                        elif isinstance(v, float):
                            sum += v
                    if sum > 1:
                        self.klog.info("An initial composition exceeds 100%.")
                        self.cancel_run = True
                        break
                    else:
                        if not base_given:
                            self.klog.info("No base given, using n2.")
                    exp[base_key] = 1 - sum

        # Calculate total number of mol in 1 cm3
        # n = PV/RT
        if 'initial_C' in self.json_file:
            self.json_file['initial_X'] = []
            sum = 0.0
            base_key = 'n2'
            base_given = False
            for key, value in self.json_file['initial_C'].items():
                if not isinstance(key, str):
                    self.klog.info(
                        'initial_C keys should be ct species names.')
                    self.cancel_run = True
                    break
                if isinstance(value, str) and value.casefold() == 'base':
                    if not base_given:
                        base_key: str = key
                        base_given = True
                    else:
                        self.klog.info(
                            f"{key} cannot be the base. It's {base_key}.")
                        self.cancel_run = True
                elif isinstance(value, float):
                    n = Q_(value, 'molecule')
                    exp = 0
                    # Setup molar fraction for each experiment for 1cm^3
                    for a in self.json_file['rc_pres']:
                        try:
                            p = Q_(a, self.json_file['pres_unit']).to('torr')
                        except ValueError as e:
                            self.cancel_run = True
                            self.klog.info('pres_unit was not recognised.')
                            self.klog.info(str(e))
                        for b in self.json_file['rc_temp']:
                            t = Q_(b, 'K')
                            if len(self.json_file['initial_X']) <= exp:
                                self.json_file['initial_X'].append({})
                            ntot = (p*Vol/(R*t)).to('molecule')
                            self.json_file['initial_X'][exp][key] = \
                                (n/ntot).magnitude
                            exp += 1
                    sum += (n/ntot).magnitude
                    if sum > 1:
                        self.klog.info(
                            "The sum of initial C exeeds the total pressure.")
                        self.cancel_run = True
                else:
                    self.klog.info('Values of initial_C should be floats.')
                    self.cancel_run = True
                    break
            for exp in self.json_file['initial_X']:
                exp[base_key] = 1 - sum

        for idx, exp in enumerate(self.json_file['initial_X']):
            self.klog.info(f"Initial composition for experiment {idx}:")
            for k, v in exp.items():
                msg = '\t'
                msg += f'{k}: {v:-.2e}'
                self.klog.info(msg)

    def check_unknown_kwords(self) -> None:
        """Check if some keys in the input are not
        reconised
        """
        for key in self.json_file:
            if key not in default_settings and\
               key not in mandatory_keys and\
               key != 'initial_X':
                self.klog.info(
                    f"{key} is an unknown keyword and will be ignored.")

    def set_default_values(self) -> None:
        """Set all the values of non-mandatory
        parameters. Default if not in user input.
        """
        for key, value in default_settings.items():
            if key not in self.json_file:
                # Replace value by enum for RNG distributions
                if 'distrib' in key:
                    value = Distrib(value)
                # Check the FreqMode
                if key == 'freq_mode':
                    value = FreqMode(value)
                elif key == 'optimizer':
                    value = Optimizers(value)
                self.json_file[key] = value
            elif not isinstance(self.json_file[key], type(value)):
                if isinstance(value, float) and \
                   isinstance(self.json_file[key], int):
                    continue
                self.klog.warning(
                    f"{key} has incorrect type. It should be {type(value)}")
                self.cancel_run = True
            # Replace value by enum for RNG distributions
            elif 'distrib' in key:  # Key is a distribution specified in JSON
                for ptype in Ptype:
                    if ptype.value in key:
                        break
                if any([self.json_file[key].casefold() == distrib.value
                        for distrib in Distrib]):
                    dist = Distrib(self.json_file[key].casefold())
                    if ptype.value in Pclass.ADDITIVE.value:
                        if dist == Distrib.LOGNORMAL or\
                           dist == Distrib.LOGUNIFORM:
                            msg = f"{key} is not allowed for this parameter."
                            self.klog.warning(msg)
                            self.cancel_run = True
                    self.json_file[key] = Distrib(
                        self.json_file[key].casefold())
                else:
                    self.klog.warning(f"{key} has unknown distribution.")
                    self.cancel_run = True
            # Replace value by enum for mode of frequencxy perturbation
            elif key == 'freq_mode':
                if any([self.json_file[key].casefold() == fm.value
                        for fm in FreqMode]):
                    self.json_file[key] = FreqMode(
                        self.json_file[key].casefold())
                else:
                    self.klog.warning(
                        f"{key} has unknown frequency perturbation mode.")
                    self.cancel_run = True
            elif key == 'optimizer':
                if any([self.json_file[key].casefold() == opt.value
                        for opt in Optimizers]):
                    self.json_file[key] = Optimizers(
                        self.json_file[key].casefold())
                else:
                    self.klog.warning(f"{key} has unknown type.")
                    self.cancel_run = True

    def set_profiles(self) -> None:
        """Read the csv files for every experiments,
        together with the error files
        """
        clean_profiles = []
        clean_errors = []
        species = []
        exp_headers = []
        if len(self.json_file['exp_profiles']) != self.n_exp:
            self.klog.info(
                "There should be one csv profile file for each TP condition.")
            self.cancel_run = True
        else:
            for p in range(len(self.json_file['rc_pres'])):
                for t in range(len(self.json_file['rc_temp'])):
                    idx: int = p*len(self.json_file['rc_temp']) + t
                    file: str = \
                        self.init_loc+self.json_file['exp_profiles'][idx]
                    file_err: str = \
                        self.init_loc+self.json_file['exp_errors'][idx]
                    clean_profiles.append({})
                    clean_errors.append({})
                    exp_headers.append([])
                    if not os.path.isfile(file) or\
                       not os.path.isfile(file_err):
                        self.klog.info(f'Could not find file {file}.')
                        self.cancel_run = True
                    else:
                        # Read experimental profiles
                        with open(file, mode='r', encoding='utf-8-sig') as f:
                            csv_DictReader = csv.DictReader(f)
                            ln = 0
                            for line in csv_DictReader:
                                if 'time' not in line:
                                    msg = "A column should be the 'time'"
                                    msg += f" in file {file}."
                                    self.klog.info(msg)
                                    self.cancel_run = True
                                else:
                                    for header in line:
                                        # Skip excluded species
                                        if header in self.json_file['exclude_sp']:
                                            continue
                                        # Consider other species
                                        if header not in species and header != 'time':
                                            species.append(header)
                                        if header not in exp_headers[-1] and header != 'time':
                                            exp_headers[-1].append(header)
                                        if ln == 0:
                                            clean_profiles[-1][header] = []
                                        try:
                                            clean_profiles[-1][header].append(
                                                float(line[header]))
                                        except TypeError as e:
                                            self.klog.debug(str(e))
                                            msg = (
                                                'Incorrect value detected' +
                                                f' line{ln} in file {file}' +
                                                f' column {header}'
                                            )
                                            self.klog.info(msg)
                                            self.cancel_run = True
                                ln += 1
                        # Read experimental profiles errors
                    with open(file_err, mode='r', encoding='utf-8-sig') as f:
                        csv_DictReader = csv.DictReader(f)
                        ln = 0
                        for line in csv_DictReader:
                            if 'time' not in line:
                                msg = "A column should be the 'time'" + \
                                    f"column in file {file_err}."
                                self.klog.info(msg)
                                self.cancel_run = True
                            else:
                                for header in line:
                                    # Skip excluded species
                                    if header in self.json_file['exclude_sp']:
                                        continue
                                    # Consider other species
                                    if ln == 0:
                                        clean_errors[-1][header] = []
                                    try:
                                        clean_errors[-1][header].append(
                                            float(line[header]))
                                    except TypeError as e:
                                        self.klog.debug(str(e))
                                        msg = (
                                            'Incorrect value detected' +
                                            f' line{ln} in file {file}' +
                                            f' column {header}'
                                        )
                                        self.klog.info(msg)
                                        self.cancel_run = True
                            ln += 1
                    # check the created profiles:
                    nstep: int = len(clean_profiles[-1]['time'])
                    if nstep != len(clean_errors[-1]['time']):
                        msg = 'Error file has a different number of values' +\
                            ' than corresponding profile.'
                        self.klog.info(msg)
                        self.cancel_run = True
                    for header, profile in clean_profiles[-1].items():
                        if len(profile) != nstep:
                            msg = f'Not enough values in profile {header}' +\
                                f' in file {file}'
                            self.klog.info(msg)
        # Transform the profiles in numpy structured arrays
        for idx, prof in enumerate(clean_profiles):
            clean_profiles[idx] = np.empty(
                shape=(len(prof), len(prof['time'])),
                dtype=float64)
            for cidx, col in enumerate(prof):
                clean_profiles[idx][cidx] = prof[col]
        self.json_file['exp_profiles'] = clean_profiles
        # Do the same with error files
        for idx, prof in enumerate(clean_errors):
            clean_errors[idx] = np.empty(
                shape=(len(prof), len(prof['time'])),
                dtype=float64)
            for cidx, col in enumerate(prof):
                clean_errors[idx][cidx] = prof[col]
        self.json_file['exp_errors'] = clean_errors

        # Modify score_sp to contain appropriate species
        if self.json_file['score_sp'] == []:
            self.json_file['score_sp'] = species
        else:
            for sp in self.json_file['score_sp']:
                if sp not in species:
                    msg = f'Specie {sp} cannot be scored' +\
                        ' because it is not in the' +\
                        ' experimental profiles.'
                    self.klog.info(msg)
                    self.cancel_run = True

        # Setting the weight for each experiment
        # default
        if len(self.json_file['w_exp']) == 0:
            self.json_file['w_exp'] = [
                1.0/self.n_exp for i in range(self.n_exp)]
        # Error in input
        elif len(self.json_file['w_exp']) != self.n_exp:
            self.klog.info(
                f"The number of weights in w_exp should be {self.n_exp}")
            self.cancel_run = True
        else:
            sum = 0.0
            for val in self.json_file['w_exp']:
                sum += val
            # Normalize the weights
            self.json_file['w_exp'] = np.array(
                [val*self.n_exp/sum for val in self.json_file['w_exp']])

        # Setup species weights for each experiment
        self.json_file['weights'] = []
        for key in self.json_file['w_species']:
            if key not in species:
                msg = f'Specie {key} cannot have a weight' +\
                    ' because it is not in the' +\
                    ' experimental profiles.'
                self.klog.info(msg)
                self.cancel_run = True
        for idx, exp_h in enumerate(exp_headers):
            sp_w_exp: NDArray[float64] = np.ones(
                shape=len(exp_h),
                dtype=float64)
            i = 0
            for sp_i in exp_h:
                # If a specie should have a score
                if sp_i in self.json_file['score_sp'] and \
                   sp_i not in self.json_file['exclude_sp']:
                    # If the specie has a specific weight
                    if sp_i in self.json_file['w_species']:
                        sp_w_exp[i] = self.json_file['w_species'][sp_i]
                    else:
                        pass

                else:
                    sp_w_exp[i] = 0.0
                i += 1
            sp_w_exp *= self.json_file['w_exp'][idx]
            self.json_file['weights'].append(sp_w_exp)

    def other_checks_to_modif(self) -> None:
        """Early implementation checks that should be improved,
        but not super important
        """
        implemented_sf: list[str] = ['weighteddif']
        if self.json_file['scoring_func'].casefold() not in implemented_sf:
            self.klog.info('Unknown scoring function. Check the spelling?')
            self.cancel_run = True
        if any([self.json_file['restart'].casefold() == rt.value
                for rt in RestartType]):
            self.json_file['restart'] = RestartType(
                self.json_file['restart'].casefold())
            self.klog.warning(
                f"'restart' set to {self.json_file['restart'].value}")
        else:
            self.klog.warning("'restart' has unknown type.")
            self.cancel_run = True

    def full_run_settings(self) -> dict[str, Any]:
        """Merge the users settings with the default values.

        Args:
            input_file (str): Path to JSON file
            klog (Logger): Logger

        Returns:
            dict: settings
        """
        self.basic_checks()
        self.create_initial_conditions()
        self.check_unknown_kwords()
        self.set_default_values()
        self.set_profiles()
        self.other_checks_to_modif()
        if self.cancel_run:
            sys.exit(-1)
        self.json_file['init_loc'] = self.init_loc
        self.json_file['workdir'] = \
            self.init_loc+self.json_file['project_name']
        self.json_file['input_file'] = self.input_file
        self.json_file['n_exp'] = self.n_exp
        self.json_file['postprocess'] = False

        return self.json_file

    def sim_settings_only(self) -> dict[str, Any]:
        """Only set the minimum amount of settings necessary
        for the simulation job to run.

        Returns:
            dict[str, Any]: settings
        """
        self.set_default_values()
        return self.json_file
