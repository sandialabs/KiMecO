"""Postprocessing simulations must be written with the rates stored in KIN_DB.

Regression: when every postprocessing (P, T) cell is already in KIN_DB, the
reuse branch of ``CoreRun.calculate_rate_coefficients`` skips MESS and leaves
``rateCoef.rc_by_pes`` empty. ``Extrapolate`` used to override
``run_simulation`` without calling ``load_rates_from_db``, so every kmopp
simulation script was rendered with ``rates_by_pes = {}`` and failed with
``ValueError: Missing rates or tbl_map for PES 0``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np

import kimeco.core as core_mod
from kimeco.core import CoreRun
from kimeco.enums import ModelStatus
from kimeco.postprocessing.extrapolate import Extrapolate
from kimeco.q_sys import JobStatus


class _FakeRateCo:
    """RateCo stand-in whose rates only exist once loaded from the DB."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.rc_by_pes: dict[int, np.ndarray] = {}
        self.tbl_map_by_pes: dict[int, dict[str, int]] = {}
        self.loaded_tables: list[str] = []

    def load_rates_from_db(self, table: str) -> None:
        self.events.append(f'load:{table}')
        self.loaded_tables.append(table)
        self.rc_by_pes = {0: np.full((1, 1, 2, 2), 1.5e3)}
        self.tbl_map_by_pes = {0: {'A': 0, 'B': 1}}


class _SpySIM:
    """SIM stand-in recording construction and the rates seen at q_up."""

    last: Any = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.kin = kwargs['kin']
        self.events: list[str] = kwargs['kin'].events
        self.events.append('sim_init')
        self.rates_at_q_up: dict[int, np.ndarray] | None = None
        _SpySIM.last = self

    def q_up(self) -> None:
        self.events.append('q_up')
        self.rates_at_q_up = dict(self.kin.rc_by_pes)


class _FakeQueue:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def add_to_q(self, **kwargs) -> None:
        self.submitted.append(kwargs)

    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.NOT_IN_QUEUE


def _extrapolate(loc: str = '/tmp', settings: dict | None = None) -> Extrapolate:
    ext = Extrapolate.__new__(Extrapolate)
    ext.prefix = 'PP'
    ext.loc = loc
    ext.base_dir = ''
    ext.settings = settings if settings is not None else {'postprocess': True}
    ext.sim_db = cast(Any, object())
    ext.qs = cast(Any, _FakeQueue())
    ext.klog = cast(Any, SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        error=lambda *a, **k: None))
    return ext


def _mdl(events: list[str], gen: int = 1, mdl_id: int = 3, **extra):
    mdl = SimpleNamespace(
        id=mdl_id, gen=gen, name=f'E{mdl_id:04d}', sop=object(),
        status=ModelStatus.KIN, origin_prefix='G',
        rateCoef=_FakeRateCo(events))
    for key, value in extra.items():
        setattr(mdl, key, value)
    return mdl


def test_extrapolate_inherits_core_run_simulation() -> None:
    # Guard against reintroducing an override that skips load_rates_from_db.
    assert 'run_simulation' not in vars(Extrapolate)
    assert Extrapolate.run_simulation is CoreRun.run_simulation


def test_rates_loaded_before_simulation_is_submitted(monkeypatch) -> None:
    monkeypatch.setattr(core_mod, 'SIM', _SpySIM)
    events: list[str] = []
    mdl = _mdl(events, gen=1, mdl_id=3, thread_id=7)

    _extrapolate().run_simulation(cast(Any, mdl))

    assert events == ['load:G0001', 'sim_init', 'q_up']
    sim = _SpySIM.last
    assert sim.rates_at_q_up is not None and 0 in sim.rates_at_q_up
    assert sim.rates_at_q_up[0].shape == (1, 1, 2, 2)
    assert sim.kwargs['gen_name'] == 'G0001'
    assert sim.kwargs['q_idx'] == 7
    assert mdl.sim is sim
    assert mdl.status == ModelStatus.SIM


def test_goat_model_loads_from_its_origin_generation_table(monkeypatch) -> None:
    # GT-n ensembles merge models from many generations: rates must be read
    # from the model's own G#### table, not from a 'PP' prefixed table.
    monkeypatch.setattr(core_mod, 'SIM', _SpySIM)
    events: list[str] = []
    mdl = _mdl(events, gen=217, mdl_id=42, thread_id=0)

    _extrapolate().run_simulation(cast(Any, mdl))

    assert mdl.rateCoef.loaded_tables == ['G0217']
    assert _SpySIM.last.kwargs['gen_name'] == 'G0217'
    assert _SpySIM.last.kwargs['loc'].endswith('/G0217')


def test_q_idx_falls_back_to_model_id_without_thread_id(monkeypatch) -> None:
    monkeypatch.setattr(core_mod, 'SIM', _SpySIM)
    events: list[str] = []
    mdl = _mdl(events, gen=1, mdl_id=5)

    _extrapolate().run_simulation(cast(Any, mdl))

    assert _SpySIM.last.kwargs['q_idx'] == 5


def test_rendered_script_contains_stored_rates(tmp_path) -> None:
    # End to end with the real SIM: the written cantera script must embed the
    # rates loaded from KIN_DB, never the empty dicts of the regression.
    (tmp_path / 'G0001' / '00').mkdir(parents=True)
    exp = SimpleNamespace(
        data=np.array([[0.0, 0.01]]),
        species=['HO2'],
        new_tpl=True,
        tpl_idx=0,
        sim_file=('tbl_map_by_pes = {tbl_map_by_pes}\n'
                  'rates_by_pes = {rates_by_pes}\n'))
    settings = {
        'postprocess': True,
        'experiments': [exp],
        'cpu_sim': 1,
        'mem_sim': 100,
        'scratch_base': str(tmp_path) + '/scratch/',
        'project_name': 'KMO_Project',
        'init_loc': str(tmp_path) + '/',
        'input_file': str(tmp_path / '_kmopp_input.json'),
    }
    ext = _extrapolate(loc=str(tmp_path), settings=settings)
    events: list[str] = []
    mdl = _mdl(events, gen=1, mdl_id=3, thread_id=0)

    ext.run_simulation(cast(Any, mdl))

    script = (tmp_path / 'G0001' / '00' / 'G0001E0003S_exp00.py').read_text()
    assert 'rates_by_pes = {}' not in script
    assert 'tbl_map_by_pes = {}' not in script
    assert "tbl_map_by_pes = {0: {'A': 0, 'B': 1}}" in script
    assert 'rates_by_pes = {0: [[[[1500.0, 1500.0]' in script
    assert len(cast(Any, ext.qs).submitted) == 1
    assert mdl.status == ModelStatus.SIM
