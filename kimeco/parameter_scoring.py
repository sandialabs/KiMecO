from __future__ import annotations

from typing import Any

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


def normalize_score_weights(settings: dict[str, Any]) -> tuple[float, float]:
    weight_theory = float(settings.get('weight_theory', 1.0))
    weight_experiments = float(settings.get('weight_experiments', 1.0))

    if weight_theory < 0.0 or weight_experiments < 0.0:
        raise ValueError('Scoring weights must be non-negative.')

    total = weight_theory + weight_experiments
    if total <= 0.0:
        return 0.5, 0.5

    return weight_theory / total, weight_experiments / total