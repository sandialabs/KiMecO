from __future__ import annotations

import pytest

from kimeco._kimeco import optimizer_prefix
from kimeco.enums import Optimizers
from kimeco.optimizers.GeneticAlgo.exponential import Exponential
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.optimizers.GeneticAlgo.tournament import Tournament
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.optimizers.NelderMead.nelder_mead_swarm import NelderMeadSwarm


def test_prefix_readable_on_classes_without_instantiation() -> None:
    """The prefix is readable on the optimizer classes without instantiation; GA
    ignores ga_type; NM has its own; legacy tokens are never returned."""
    # -- test_prefix_readable_on_classes_without_instantiation
    # All prefixes are class attributes: no instance is constructed.
    assert GeneticAlgorithm.prefix == 'G'
    assert Exponential.prefix == 'G'
    assert Tournament.prefix == 'G'
    assert NelderMead.prefix == 'NM'
    assert NelderMeadSwarm.prefix == 'NMSG'

    # -- test_optimizer_prefix_ga_ignores_ga_type
    assert optimizer_prefix({'optimizer': Optimizers.GA}) == 'G'
    assert optimizer_prefix(
        {'optimizer': Optimizers.GA, 'ga_type': 'tournament'}) == 'G'
    assert optimizer_prefix(
        {'optimizer': Optimizers.GA, 'ga_type': 'exponential'}) == 'G'

    # -- test_optimizer_prefix_nm
    assert optimizer_prefix({'optimizer': Optimizers.NM}) == 'NM'

    # -- test_optimizer_prefix_never_returns_legacy_tokens
    for opt in (Optimizers.GA, Optimizers.NM):
        result = optimizer_prefix({'optimizer': opt})
        assert result != 'GT'
        assert not result.startswith('X')


def test_optimizer_prefix_unknown_raises() -> None:
    with pytest.raises(NotImplementedError):
        optimizer_prefix({'optimizer': 'bmcmc'})
