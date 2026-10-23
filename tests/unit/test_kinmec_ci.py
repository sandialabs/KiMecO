"""CI-safe tests for ``KiMec`` (cantera mechanism writer): reaction equations,
the rate-coefficient template grid, its sync to the rate shape, and the
grid defaults read by ``__init__`` (``cantera.Solution`` faked).
"""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest

from kimeco.bimolecular import Bimolecular
from kimeco.default_settings import default_settings
from kimeco.kinmec import KiMec
from kimeco.well import Well


# ===========================================================================
# get_reaction_eq
# ===========================================================================
def _eq_kinmec_stub() -> KiMec:
    # get_reaction_eq does not use instance state.
    return cast(Any, KiMec.__new__(KiMec))


def test_get_reaction_eq_dummy_and_bimol_cases() -> None:
    """Dummy bimolecular product or reactant and a non-dummy bimolecular with
    fragments all give "A => B + C" style equations."""
    # -- test_get_reaction_eq_well_to_dummy_bimol_product_keeps_arrow
    kinmec = _eq_kinmec_stub()
    reactant = Well(name="A", pes_ids=[0])
    product = Bimolecular(name="CH2O+CH2O+OH", pes_ids=[0])
    product.dummy = True

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "A => CH2O + CH2O + OH"

    # -- test_get_reaction_eq_dummy_bimol_reactant_to_well
    kinmec = _eq_kinmec_stub()
    reactant = Bimolecular(name="CH2O+OH", pes_ids=[0])
    reactant.dummy = True
    product = Well(name="A", pes_ids=[0])

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "CH2O + OH => A"

    # -- test_get_reaction_eq_well_to_non_dummy_bimol_product
    kinmec = _eq_kinmec_stub()
    reactant = Well(name="A", pes_ids=[0])
    product = Bimolecular(name="B+C", pes_ids=[0])
    product.set_fragments([
        Well(name="B", pes_ids=[]),
        Well(name="C", pes_ids=[]),
    ])

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "A => B + C"


# ===========================================================================
# Rate-coefficient template grid and its sync to the rates
# ===========================================================================
def _grid_kinmec_stub(pres: list[float],
                 temp: list[float],
                 settings: dict[str, Any]) -> Any:
    """Build a KiMec without running __init__ (which needs a cantera file).

    Only the attributes used by the grid-sync logic are populated, and the
    template rebuild hook is replaced by a call counter so the test does not
    require a full SOP.
    """
    kinmec = cast(Any, KiMec.__new__(KiMec))
    kinmec.pres = pres
    kinmec.temp = temp
    kinmec.settings = settings
    kinmec.rc_tpl = kinmec._build_rc_tpl()
    kinmec.rebuilt = 0

    def _count_rebuild() -> None:
        kinmec.rebuilt += 1

    kinmec.create_reactions_templates = _count_rebuild
    return kinmec


def _settings() -> dict[str, Any]:
    return {
        "rc_pres": [1.0, 2.0],
        "rc_temp": [300.0, 400.0, 500.0],
        "pp_pres": [1.0],
        "pp_temp": [300.0, 400.0, 500.0],
        "pres_unit": "bar",
    }


def test_rc_template_fields_and_pressure_label() -> None:
    """The rc template has one field per (P, T) point; the reaction template
    labels pressures in bar whatever pres_unit says."""
    # -- test_build_rc_tpl_emits_one_field_per_grid_point
    kinmec = _grid_kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    assert kinmec.rc_tpl.count("rc_") == 6
    assert "rc_0_0: {rates[0][0]}" in kinmec.rc_tpl
    assert "rc_1_2: {rates[1][2]}" in kinmec.rc_tpl

    # -- test_reaction_template_labels_pressure_in_bar
    # Grids are always stored in bar, so the Pgrid label must be 'bar'
    # regardless of the user-facing 'pres_unit' setting (the previous code
    # labelled bar values with pres_unit, e.g. '0.1 torr', breaking the
    # rate lookup at simulation time).
    kinmec = _grid_kinmec_stub(pres=[0.1, 1.0],
                          temp=[750.0, 800.0],
                          settings={"pres_unit": "torr"})

    tpl = kinmec.create_reaction_template(
        reactant=Well(name="A", pes_ids=[0]),
        product=Well(name="B", pes_ids=[0]),
    )

    assert "torr" not in tpl
    assert "0.1 bar" in tpl
    assert "1.0 bar" in tpl
    assert "750.0 K" in tpl


def test_sync_grid_to_rates() -> None:
    """Rates on the pp grid switch the templates to it; rates on the current
    grid are a no-op; rates matching no known grid raise ValueError."""
    # -- test_sync_switches_to_pp_grid_when_rates_are_postprocess_shaped
    # Templates default to the rc grid (2 pressures) but the injected rates
    # were evaluated on the pp grid (1 pressure): the previous code indexed
    # rates[1] on a size-1 axis and raised IndexError.
    kinmec = _grid_kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    pp_rates = {0: np.zeros((1, 3, 2, 2))}
    kinmec._sync_grid_to_rates(pp_rates)

    assert kinmec.pres == [1.0]
    assert kinmec.temp == [300.0, 400.0, 500.0]
    assert kinmec.rc_tpl.count("rc_") == 3
    assert kinmec.rebuilt == 1

    # -- test_sync_is_noop_when_rates_match_current_grid
    kinmec = _grid_kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    rc_rates = {0: np.zeros((2, 3, 2, 2))}
    kinmec._sync_grid_to_rates(rc_rates)

    assert kinmec.pres == [1.0, 2.0]
    assert kinmec.rc_tpl.count("rc_") == 6
    assert kinmec.rebuilt == 0

    # -- test_sync_raises_when_rates_match_no_known_grid
    kinmec = _grid_kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    mismatched_rates = {0: np.zeros((5, 7, 2, 2))}
    with pytest.raises(ValueError):
        kinmec._sync_grid_to_rates(mismatched_rates)


# ===========================================================================
# __init__ grid defaults (cantera.Solution faked)
# ===========================================================================
class _FakeSolution:
    """Stand-in for ``cantera.Solution`` so ``KiMec.__init__`` can run without
    a real mechanism file. ``__init__`` reads the settings grid keys (the code
    under test) before touching the Solution, and only calls ``.species()`` and
    ``.reactions()`` on it, both of which we return empty.
    """

    def species(self) -> list[Any]:
        return []

    def reactions(self) -> list[Any]:
        return []


@pytest.fixture
def _patch_solution(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``file`` is a dummy string that is never opened because Solution is faked.
    monkeypatch.setattr(
        "kimeco.kinmec.ct.Solution",
        lambda file: _FakeSolution(),
    )


@pytest.mark.usefixtures("_patch_solution")
def test_init_grid_defaults() -> None:
    """postprocess False: no rc grid gives empty defaults (regression KeyError),
    a provided rc grid is kept; postprocess True reads the pp grid, ignoring a
    missing rc grid, and an empty pp grid gives empty defaults."""
    # -- test_init_without_rc_grid_does_not_raise_keyerror
    # Regression: postprocess=False with no rc_pres/rc_temp used to raise
    # KeyError; the fix uses settings.get(..., []) so the grid defaults empty.
    settings = {**default_settings, "postprocess": False}
    settings.pop("rc_pres", None)
    settings.pop("rc_temp", None)

    kinmec = KiMec(file="mech.yaml", settings=settings)

    assert kinmec.pres == []
    assert kinmec.temp == []
    assert kinmec.rc_tpl == ""

    # -- test_init_postprocess_false_preserves_provided_rc_grid
    settings = {
        **default_settings,
        "postprocess": False,
        "rc_pres": [1.0, 2.0],
        "rc_temp": [300.0, 400.0, 500.0],
    }

    kinmec = KiMec(file="mech.yaml", settings=settings)

    assert kinmec.pres == [1.0, 2.0]
    assert kinmec.temp == [300.0, 400.0, 500.0]
    # 2 pressures x 3 temperatures -> 6 substitution fields.
    assert kinmec.rc_tpl.count("rc_") == 6
    assert "rc_0_0: {rates[0][0]}" in kinmec.rc_tpl
    assert "rc_1_2: {rates[1][2]}" in kinmec.rc_tpl

    # -- test_init_postprocess_true_reads_pp_grid_and_ignores_missing_rc
    settings = {
        **default_settings,
        "postprocess": True,
        "pp_pres": [1.0],
        "pp_temp": [300.0, 400.0],
    }
    settings.pop("rc_pres", None)
    settings.pop("rc_temp", None)

    kinmec = KiMec(file="mech.yaml", settings=settings)

    assert kinmec.pres == [1.0]
    assert kinmec.temp == [300.0, 400.0]

    # -- test_init_postprocess_true_with_default_empty_pp_grid
    settings = {**default_settings, "postprocess": True}

    kinmec = KiMec(file="mech.yaml", settings=settings)

    assert kinmec.pres == []
    assert kinmec.temp == []
    assert kinmec.rc_tpl == ""


@pytest.mark.usefixtures("_patch_solution")
def test_mechanism_section_style_construction_succeeds() -> None:
    # Mirrors the GUI mechanism-section trigger: build from default settings
    # with postprocess disabled and confirm species/reactions are readable.
    settings = {**default_settings}
    settings["postprocess"] = False

    kinmec = KiMec(file="mech.yaml", settings=settings)

    assert kinmec.species == []
    assert kinmec.reactions == []



def test_create_reactions_templates_all_pairs_without_self() -> None:
    from types import SimpleNamespace
    km = KiMec.__new__(KiMec)
    w1, w2 = SimpleNamespace(name='W1'), SimpleNamespace(name='W2')
    b1, b2 = SimpleNamespace(name='B1'), SimpleNamespace(name='B2')
    km.SOP = cast(Any, SimpleNamespace(wells=[w1, w2], bimolecular=[b1, b2]))
    km.new_reactions_tpls = {}
    calls: list[tuple[str, str]] = []

    def _tpl(reactant: Any, product: Any) -> str:
        calls.append((reactant.name, product.name))
        return f'{reactant.name}->{product.name}'

    km.create_reaction_template = _tpl
    km.create_reactions_templates()
    expected = [('W1', 'W2'), ('W2', 'W1'),
                ('W1', 'B1'), ('W1', 'B2'), ('W2', 'B1'), ('W2', 'B2'),
                ('B1', 'W1'), ('B1', 'W2'), ('B2', 'W1'), ('B2', 'W2'),
                ('B1', 'B2'), ('B2', 'B1')]
    assert calls == expected
    assert km.new_reactions_tpls == {k: f'{k[0]}->{k[1]}' for k in expected}
