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
        n_active_p = np.sum(~np.isclose(
            np.array([sop.parameters_names[p] for p in sop.parameters_names]),
            np.array([self.SOP.parameters_names[p] for p in self.SOP.parameters_names])
        ))
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

    def fscore(self,
               mdl: Model) -> None:
        """Fast score calculation, when a model is reconstructed.
        Calculate the score of a model as
        the weighted average of the scores of the experiments,
        plus the score of the theory.
        """
        t_score = self.score_theory(mdl.sop)
        tot_exp_weights = np.sum(
            [exp.weight for exp in self.settings['experiments']]
        )
        exp_score = np.sum([
            mdl.experiment_scores[idx] * exp.weight/tot_exp_weights
            for idx, exp in enumerate(self.settings['experiments'])
        ])
        mdl.theory_score = t_score
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

    @staticmethod
    def _format_value(value: float) -> str:
        """Format a score value.

        Uses 3 decimal places, or scientific notation with 2 decimals when
        the magnitude is >= 1000. Non-finite values render as 'nan'/'inf'.

        Args:
            value: the value to format.

        Returns:
            str: the formatted value.
        """
        if np.isnan(value):
            return 'nan'
        if np.isinf(value):
            return 'inf' if value > 0 else '-inf'
        if abs(value) >= 1000.0:
            return f'{value:.2E}'
        return f'{value:.3f}'

    @classmethod
    def _format_score_columns(cls,
                              columns: list[tuple[str, float]],
                              width: int,
                              max_cols: int = 7) -> list[str]:
        """Return header/value line pairs for the given columns.

        Columns are wrapped so that no line holds more than ``max_cols``
        columns. Every column uses the same ``width`` so that the columns
        of successive header/value pairs line up into a single grid.
        Consecutive header/value pairs are separated by a single blank line.

        Args:
            columns: list of (header, value) tuples.
            width: uniform column width applied to every column.
            max_cols: maximum number of columns per line.

        Returns:
            list[str]: alternating header and value lines.
        """
        lines: list[str] = []
        for start in range(0, len(columns), max_cols):
            if lines:
                lines.append('')
            chunk = columns[start:start + max_cols]
            header = ' '.join(
                f'{name:>{width}}' for name, _ in chunk
            )
            values = ' '.join(
                f'{cls._format_value(value):>{width}}' for _, value in chunk
            )
            lines.append(header)
            lines.append(values)
        return lines

    def _breakdown_columns(
        self,
        models: list[Model],
    ) -> tuple[list[tuple[str, float]] | None, float]:
        """Build the (header, value) columns averaged over ``models``.

        Args:
            models: models to average the score contributors over.

        Returns:
            tuple: the list of columns and the average weighted score, or
            (None, nan) when no valid (finite-score) model is available.
        """
        experiments = self.settings.get('experiments', [])
        valid = [
            m for m in models
            if m is not None and np.isfinite(m.score)
        ]
        if not valid:
            return None, float('nan')

        def avg(values: list[float]) -> float:
            finite = [v for v in values if np.isfinite(v)]
            return float(np.average(finite)) if finite else float('nan')

        theory_avg = avg([m.theory_score for m in valid])
        exp_avg = avg([m.experiment_score for m in valid])

        columns: list[tuple[str, float]] = [
            ('THEORY', theory_avg),
            ('EXP', exp_avg),
        ]
        for exp in experiments:
            per_mdl = [
                float(m.sop.scores.get(exp.name, float('nan')))
                for m in valid
            ]
            columns.append((exp.name, avg(per_mdl)))

        total_avg = avg([m.score for m in valid])
        return columns, total_avg

    def _columns_width(self, columns: list[tuple[str, float]]) -> int:
        """Return the uniform column width required for ``columns``."""
        return max(
            6,
            max(len(name) for name, _ in columns),
            max(len(self._format_value(v)) for _, v in columns),
        )

    def breakdown_width(self, models: list[Model]) -> int | None:
        """Return the column width a breakdown of ``models`` would use.

        Returns None when there is no valid model so callers can fall back
        to per-block sizing.
        """
        columns, _ = self._breakdown_columns(models)
        if columns is None:
            return None
        return self._columns_width(columns)

    def format_score_breakdown(self,
                               models: list[Model],
                               label: str,
                               width: int | None = None) -> str:
        """Build a multi-line log block summarizing the score contributors
        averaged over the provided models.

        Layout:
            - an empty first line (so the logger timestamp stands alone)
            - a label line annotated with '(species weighting only)'
            - a block of header/value pairs for THEORY, EXP and the score of
              each experiment (species-weighted, not experiment-weighted),
              wrapped to 7 columns
            - two blank lines
            - the average weighted score

        Args:
            models: models to average the contributors over.
            label: header label identifying the model set (e.g. 'GOAT').
            width: optional uniform column width to share across blocks. When
                None the width is computed from this block's own values.

        Returns:
            str: the formatted multi-line block.
        """
        columns, total_avg = self._breakdown_columns(models)

        if columns is None:
            return (
                f'\n[{label} (species weighting only)]\n'
                'No scored models to report.'
            )

        if width is None:
            width = self._columns_width(columns)
        else:
            width = max(width, self._columns_width(columns))

        lines: list[str] = ['', f'[{label} (species weighting only)]']
        lines.extend(self._format_score_columns(columns, width))
        lines.extend(['', ''])
        lines.append(
            f'WEIGHTED AVERAGE SCORE: {self._format_value(total_avg)}'
        )
        return '\n'.join(lines)
