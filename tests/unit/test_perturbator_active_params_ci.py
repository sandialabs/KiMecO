from kimeco.Perturbators.perturbator import Perturbator
from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP


def _build_perturbator(active_params: list[str], log_path: str) -> tuple[Perturbator, dict]:
    settings = {
        "active_p": active_params,
    }
    sop = SOP(score_species=[])
    pert = Perturbator(
        settings=settings,
        initial_SOP=sop,
        klog=KMOLogger(filename=log_path),
    )
    return pert, settings


def test_active_parameters_are_not_refreshed_when_settings_list_is_reassigned(
    tmp_path,
) -> None:
    pert, settings = _build_perturbator(
        active_params=["old_param"],
        log_path=str(tmp_path / "pert.log"),
    )

    settings["active_p"] = ["new_param"]

    assert pert.select == ["old_param"]
    assert pert.select != settings["active_p"]


def test_active_parameters_follow_in_place_mutation_of_original_list(tmp_path) -> None:
    original_active = ["p0"]
    pert, settings = _build_perturbator(
        active_params=original_active,
        log_path=str(tmp_path / "pert2.log"),
    )

    original_active.append("p1")

    assert settings["active_p"] == ["p0", "p1"]
    assert pert.select == ["p0", "p1"]
