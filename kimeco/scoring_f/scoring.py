from kimeco.parameters import SOP
import numpy as np
from numpy.typing import NDArray
from typing import Any
from kimeco.experiments.experiment import Experiment
from kimeco.model import Model
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Pclass, Ptype


def get_parameter_type(param: str) -> Ptype:
    suffix = param.split(dbs)[-1]
    for ptype in sorted(Ptype, key=lambda item: len(item.value), reverse=True):
        if suffix.startswith(ptype.value):
            return ptype
    raise ValueError(f"Unknown parameter type for '{param}'.")


def get_parameter_uncertainty_scale(
    reference_values: dict[str, float],
    reference_uncertainties: dict[str, float],
    param: str,
) -> float:
    uncertainty = float(reference_uncertainties[param])
    reference_value = float(reference_values[param])
    ptype = get_parameter_type(param)

    if ptype.value in Pclass.ADDITIVE.value:
        scale = uncertainty
    elif ptype.value in Pclass.PERCENT.value:
        scale = uncertainty * reference_value
    elif ptype.value in Pclass.MULTIPLICATIVE.value:
        scale = (uncertainty - 1.0) * reference_value
    else:
        raise TypeError(f"Unknown parameter type '{ptype.value}'.")

    if scale == 0.0:
        raise ValueError(f"Zero uncertainty scale for parameter '{param}'.")
    return float(scale)


class Scoring:
    def __init__(self,
                 settings: dict[str, Any],
                 initial_SOP) -> None:
        self.settings: dict[str, Any] = settings
        self.SOP = initial_SOP

    def set_active_p(self, active_p: list[str]) -> None:
        self.settings['active_p'] = active_p

    def score_theory(self,
                     sop: SOP) -> float:
        """Calculate the score of a SOP as the
        distance to the initial SOP in the active parameters space,
        normalized by the corresponding uncertainty."""

        t_score = 0.0
        n_active_p = len(self.settings["active_p"])
        if n_active_p == 0:
            # During first sensitivity pass, no active parameters are set yet.
            # Theory term must be neutral so SA can rank perturbations.
            return 0.0
        for p in self.settings["active_p"]:
            score = sop.parameters_names[p] - self.SOP.parameters_names[p]
            score /= get_parameter_uncertainty_scale(
                reference_values=self.SOP.parameters_names,
                reference_uncertainties=self.SOP.uncertainties,
                param=p
            )
            score = score**2
            score = score/n_active_p
            t_score += score
        return t_score

    def score(self,
              mdl: Model) -> None:
        """Calculate the score of a model as
        the weighted average of the scores of the experiments,
        plus the score of the theory.

        Args:
            mdl (Model): Model object
        """
        t_score = self.score_theory(mdl.sop)
        mdl.theory_score = t_score
        exp_score = 0
        exp_divider = np.sum(
            [exp.weight for exp in self.settings['experiments']]
            )
        for idx, exp in enumerate(self.settings['experiments']):
            sim_prof = mdl.sim.profiles[idx]
            if sim_prof is None:
                raise IndexError(
                    f'Missing simulation profile for exp {idx}'
                )
            mdl.sop.scores[exp.name] = self.score_experiment(sim_prof, exp)
            exp_score += exp.weight/exp_divider * mdl.sop.scores[exp.name]
        mdl.experiment_score = exp_score
        score_divider = (
            self.settings['weight_theory'] +
            self.settings['weight_experiments']
        )
        if score_divider == 0:
            # Keep the run numerically stable with a neutral split.
            weight_theory = 0.5
            weight_experiments = 0.5
        else:
            weight_theory = self.settings['weight_theory'] / score_divider
            weight_experiments = (
                self.settings['weight_experiments'] / score_divider
            )
        total_score = (
            t_score * weight_theory +
            exp_score * weight_experiments
        )
        mdl.score = total_score

    def score_experiment(self,
                         sim_profile: NDArray,
                         exp: Experiment) -> float:
        """Score a single experiment.

        Args:
            sim_profile (NDArray): Row-oriented profile with row 0 as time.
            exp (Experiment): Experiment containing reference data, errors,
                per-species weights and experiment weight.

        Returns:
            float: scalar score of the experiment.
        """
        if exp.data is None or exp.error is None:
            raise ValueError(
                f'Missing experimental data/error for {exp.name}.'
            )
        if sim_profile.shape[0] == exp.data.shape[0]:
            sim_conc = sim_profile[1:]
        else:
            # Legacy SIM stores concentration-only arrays.
            sim_conc = sim_profile
        exp_conc: NDArray = exp.data[1:]
        exp_err: NDArray = exp.error[1:]
        dif: NDArray = np.average(
            np.abs(((exp_conc - sim_conc)**2)/(exp_err**2)),
            axis=1
        )
        exp_score: float = 0.0
        sp_weights = getattr(exp, 'sp_weights', None)
        if sp_weights is not None:
            sp_divider = np.sum(sp_weights)
            if sp_divider == 0:
                exp_score = float(np.average(dif))
            else:
                exp_score = float(np.average(dif * sp_weights/sp_divider))
        else:
            exp_score = float(np.average(dif))
        return exp_score
