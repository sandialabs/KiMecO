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
from kimeco.experiments.t_profile import TimeProfile
from kimeco.scoring_f.weighteddif import WeightedDif


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

    def _global_pres_unit(self) -> str:
        """Return the canonical pressure unit used internally."""
        return str(
            self.json_file.get('pres_unit', default_settings['pres_unit'])
        )

    def _normalized_exp_pressure(self,
                                 exp_cfg: dict[str, Any]) -> float:
        """Normalize experiment pressure to the global pressure unit."""
        src_unit = exp_cfg.get('pres_unit', self._global_pres_unit())
        try:
            p_value = float(exp_cfg['pres'])
        except (TypeError, ValueError):
            raise ValueError('Experiment pressure should be numeric.')
        try:
            p_q = Q_(p_value, str(src_unit))
            return float(p_q.to(self._global_pres_unit()).magnitude)
        except Exception:
            raise ValueError(f"Unknown pressure unit: {src_unit}")

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
        """Check if the experiments inputs are without error
        """
        # Has mandatory keys?
        for key, value in mandatory_keys.items():
            if key not in self.json_file:
                self.klog.info(f"{key} is a mandatory keyword.")
                self.cancel_run = True
                continue
            if not isinstance(self.json_file[key], type(value)):
                self.klog.info(
                    f"{key} has incorrect type. Type should be {type(value)}"
                )
                self.cancel_run = True

        if 'experiments' in self.json_file:
            if len(self.json_file['experiments']) == 0:
                self.klog.info("experiments should contain at least one item.")
                self.cancel_run = True
            for idx, exp in enumerate(self.json_file['experiments']):
                if not isinstance(exp, dict):
                    self.klog.info(f"Experiment {idx} should be a dictionary.")
                    self.cancel_run = True
                    continue
                required = [
                    'temp',
                    'pres',
                    'cantera_tpl',
                    'scoring_func',
                    'data_file',
                    'error_file',
                ]
                for key in required:
                    if key not in exp:
                        self.klog.info(
                            f"Experiment {idx} missing mandatory key '{key}'."
                        )
                        self.cancel_run = True
                has_ratio = 'initial_ratio' in exp
                has_conc = 'initial_concentration' in exp
                if has_ratio == has_conc:
                    self.klog.info(
                        f"Experiment {idx} should define exactly one of "
                        "initial_ratio or initial_concentration."
                    )
                    self.cancel_run = True
                if 'weight' in exp and not isinstance(
                        exp['weight'],
                        (float, int)):
                    self.klog.info(
                        f"Experiment {idx} weight should be numeric."
                    )
                    self.cancel_run = True
                if 'pres_unit' in exp and not isinstance(
                        exp['pres_unit'],
                        str):
                    self.klog.info(
                        f"Experiment {idx} pres_unit should be a string."
                    )
                    self.cancel_run = True

        if 'pres_unit' not in self.json_file:
            self.json_file['pres_unit'] = default_settings['pres_unit']
        self.klog.info(
            f"Pressure unit in input assumed in {self.json_file['pres_unit']}")

    def _validate_tpl(self,
                      tpl_path: str) -> str:
        if not os.path.isfile(tpl_path):
            raise FileNotFoundError(f"Cantera tpl file {tpl_path} not found.")
        with open(tpl_path, mode='r') as f:
            cantera_tpl: str = f.read()
        if not cantera_tpl:
            raise ValueError(f"Cantera tpl file {tpl_path} is empty.")
        import string as _string
        parsed_keys = frozenset(
            field_name
            for _, field_name, _, _ in _string.Formatter().parse(cantera_tpl)
            if field_name is not None
        )
        missing = TimeProfile.REQUIRED_TPL_KEYS - parsed_keys
        if missing:
            msg: str = "Missing keywords in Cantera tpl: "
            msg += ", ".join(sorted(missing))
            raise ValueError(msg)
        return cantera_tpl

    def _initial_ratio_from_exp(self,
                                exp_cfg: dict[str, Any]) -> dict[str, float]:
        base_key = 'n2'
        if 'initial_ratio' in exp_cfg:
            ratio: dict[str, float] = {}
            sum_ratio: float = 0.0
            base_given = False
            for key, value in exp_cfg['initial_ratio'].items():
                if isinstance(value, str) and value.casefold() == 'base':
                    if base_given:
                        raise ValueError('Two base species given.')
                    base_key = key
                    base_given = True
                    continue
                if not isinstance(value, (float, int)):
                    raise ValueError('initial_ratio values should be numeric.')
                ratio[key] = float(value)
                sum_ratio += float(value)
            if sum_ratio > 1.0:
                raise ValueError('An initial composition exceeds 100%.')
            ratio[base_key] = 1.0 - sum_ratio
            return ratio

        ratio = {}
        sum_ratio = 0.0
        base_given = False
        p = Q_(
            self._normalized_exp_pressure(exp_cfg),
            self._global_pres_unit()
        )
        p = p.to('torr')
        t = Q_(exp_cfg['temp'], 'K')
        ntot = (p*Vol/(R*t)).to('molecule')
        for key, value in exp_cfg['initial_concentration'].items():
            if isinstance(value, str) and value.casefold() == 'base':
                if base_given:
                    raise ValueError('Two base species given.')
                base_key = key
                base_given = True
                continue
            if not isinstance(value, (float, int)):
                raise ValueError(
                    'initial_concentration values should be numeric.'
                )
            n = Q_(float(value), 'molecule')
            ratio[key] = float((n/ntot).magnitude)
            sum_ratio += ratio[key]
        if sum_ratio > 1.0:
            raise ValueError(
                'The sum of initial_concentration exceeds total pressure.'
            )
        ratio[base_key] = 1.0 - sum_ratio
        return ratio

    def check_unknown_kwords(self) -> None:
        """Check if some keys in the input are not
        reconised
        """
        for key in self.json_file:
            if key not in default_settings and\
               key not in mandatory_keys:
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

    def create_experiments(self) -> None:
        """Create TimeProfile experiment objects from input JSON."""
        experiments: list[TimeProfile] = []
        profiles: list[NDArray[float64]] = []
        errors: list[NDArray[float64]] = []
        weights: list[NDArray[float64]] = []
        initial_x: list[dict[str, float]] = []
        raw_w: list[float] = []
        rc_temp: set[float] = set()
        rc_pres: set[float] = set()

        for idx, exp_cfg in enumerate(self.json_file['experiments']):
            try:
                data_path = self.init_loc + exp_cfg['data_file']
                err_path = self.init_loc + exp_cfg['error_file']
                tpl_path = self.init_loc + exp_cfg['cantera_tpl']
                tpl_content = self._validate_tpl(tpl_path)
                ratio = self._initial_ratio_from_exp(exp_cfg)

                data_headers, data = TimeProfile.read_data(file=data_path)
                err_headers, err = TimeProfile.read_data(file=err_path)
                TimeProfile.validate_pair(
                    data_headers=data_headers,
                    data=data,
                    error_headers=err_headers,
                    error=err,
                    data_file=data_path,
                    error_file=err_path,
                )
                species = data_headers[1:]
                if exp_cfg['scoring_func'].casefold() != 'weighteddif':
                    raise ValueError(
                        f"Unknown scoring function: {exp_cfg['scoring_func']}"
                    )
                sf = WeightedDif(settings=self.json_file)

                new_tpl = True
                tpl_idx = 0
                for idxprev_exp, prev_exp in enumerate(experiments):
                    if prev_exp.sim_file == tpl_content:
                        new_tpl = False
                        tpl_idx = idxprev_exp
                        break

                normalized_pres = self._normalized_exp_pressure(exp_cfg)

                exp = TimeProfile(
                    temp=float(exp_cfg['temp']),
                    pres=normalized_pres,
                    composition=ratio,
                    data_file=data_path,
                    error_file=err_path,
                    scoring=sf,
                    sim_file=tpl_content,
                    settings=self.json_file,
                    klog=self.klog,
                    species=species,
                    weight=float(exp_cfg.get('weight', 1.0)),
                    data=data,
                    error=err,
                    new_tpl=new_tpl,
                    tpl_idx=tpl_idx
                )

                sp_weights = np.ones(shape=len(species), dtype=float64)
                w_species = exp_cfg.get(
                    'w_species',
                    self.json_file['w_species']
                )
                for sidx, sp in enumerate(species):
                    if sp in w_species:
                        sp_weights[sidx] = float(w_species[sp])
                exp.sp_weights = sp_weights

                experiments.append(exp)
                profiles.append(data)
                errors.append(err)
                weights.append(sp_weights)
                raw_w.append(exp.weight)
                initial_x.append(ratio)
                rc_temp.add(exp.T)
                rc_pres.add(exp.P)
            except Exception as e:
                self.klog.info(f"Experiment {idx} is invalid: {e}")
                self.cancel_run = True

        if len(experiments) == 0:
            self.klog.info('No valid experiment found in input.')
            self.cancel_run = True
            return

        w_sum = float(np.sum(raw_w))
        norm_exp_w = [w * len(raw_w) / w_sum for w in raw_w]
        for idx, exp in enumerate(experiments):
            exp.weight = norm_exp_w[idx]
            weights[idx] = weights[idx] * exp.weight

        self.n_exp = len(experiments)
        self.json_file['experiments'] = experiments
        self.json_file['exp_profiles'] = profiles
        self.json_file['exp_errors'] = errors
        self.json_file['weights'] = weights
        self.json_file['initial_X'] = initial_x
        self.json_file['rc_temp'] = sorted(list(rc_temp))
        self.json_file['rc_pres'] = sorted(list(rc_pres))
        self.json_file['w_exp'] = norm_exp_w
        self.json_file['to_watch'] = [exp.species for exp in experiments]

        self.json_file['scoring_func'] = 'weighteddif'

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
        self.check_unknown_kwords()
        self.set_default_values()
        self.create_experiments()
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
