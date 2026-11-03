"""The Reactor line of the shipped Cantera simulation templates runs with the installed Cantera.

Cantera 3.2.0 renamed the Reactor constructor argument ``contents`` to ``phase``:
``ct.ConstPressureMoleReactor(contents=gas, ...)`` raises ``TypeError`` there. Each
template is only rendered and run inside a Slurm simulation job, so a stale keyword
would surface only at run time. These tests extract the ``reactor = ...`` and
``net = ...`` lines of each template and execute them against a small
``ct.Solution``.
"""
import re
from pathlib import Path

import cantera as ct
import pytest

from kimeco.templates.sim_arr_tpl import ctjobtpl

REPO_ROOT = Path(__file__).resolve().parents[2]

REACTOR_LINE = re.compile(r'^reactor = ct\.ConstPressureMoleReactor\(.*\)\s*$', re.M)
NET_LINE = re.compile(r'^net = ct\.ReactorNet\(\[reactor\]\)\s*$', re.M)


def _template_sources():
    return {
        'kimeco.templates.sim_arr_tpl.ctjobtpl': ctjobtpl,
        'example/concentration_time_isobar_adiabatic.tpl':
            (REPO_ROOT / 'example' / 'concentration_time_isobar_adiabatic.tpl').read_text(),
        'tests/parse_pes/dme/ct.tpl':
            (REPO_ROOT / 'tests' / 'parse_pes' / 'dme' / 'ct.tpl').read_text(),
    }


def _reactor_lines(source):
    reactor = REACTOR_LINE.findall(source)
    net = NET_LINE.findall(source)
    assert len(reactor) == 1, f'expected one Reactor line, found {reactor}'
    assert len(net) == 1, f'expected one ReactorNet line, found {net}'
    return reactor[0].strip(), net[0].strip()


def _run_reactor_lines(source):
    reactor_line, net_line = _reactor_lines(source)
    gas = ct.Solution('gri30.yaml')
    gas.TPX = 1000.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'
    namespace = {'ct': ct, 'gas': gas}
    exec(reactor_line + '\n' + net_line, namespace)
    return namespace


@pytest.mark.parametrize('name', sorted(_template_sources()))
def test_template_reactor_constructs_with_installed_cantera(name):
    namespace = _run_reactor_lines(_template_sources()[name])
    reactor = namespace['reactor']
    assert isinstance(reactor, ct.ConstPressureMoleReactor)
    assert reactor.name == 'r1'
    assert reactor.energy_enabled is False
    assert isinstance(namespace['net'], ct.ReactorNet)


@pytest.mark.parametrize('name', sorted(_template_sources()))
def test_template_reactor_uses_phase_keyword(name):
    reactor_line, _ = _reactor_lines(_template_sources()[name])
    assert 'phase=gas' in reactor_line
    assert 'contents=' not in reactor_line
