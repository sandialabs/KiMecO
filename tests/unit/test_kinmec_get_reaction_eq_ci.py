from __future__ import annotations

from typing import Any, cast

from kimeco.bimolecular import Bimolecular
from kimeco.kinmec import KiMec
from kimeco.well import Well


def _kinmec_stub() -> KiMec:
    # get_reaction_eq does not use instance state.
    return cast(Any, KiMec.__new__(KiMec))


def test_get_reaction_eq_well_to_dummy_bimol_product_keeps_arrow() -> None:
    kinmec = _kinmec_stub()
    reactant = Well(name="A", pes_ids=[0])
    product = Bimolecular(name="CH2O+CH2O+OH", pes_ids=[0])
    product.dummy = True

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "A => CH2O + CH2O + OH"


def test_get_reaction_eq_dummy_bimol_reactant_to_well() -> None:
    kinmec = _kinmec_stub()
    reactant = Bimolecular(name="CH2O+OH", pes_ids=[0])
    reactant.dummy = True
    product = Well(name="A", pes_ids=[0])

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "CH2O + OH => A"


def test_get_reaction_eq_well_to_non_dummy_bimol_product() -> None:
    kinmec = _kinmec_stub()
    reactant = Well(name="A", pes_ids=[0])
    product = Bimolecular(name="B+C", pes_ids=[0])
    product.set_fragments([
        Well(name="B", pes_ids=[]),
        Well(name="C", pes_ids=[]),
    ])

    eq = kinmec.get_reaction_eq(reactant=reactant, product=product)

    assert eq == "A => B + C"
