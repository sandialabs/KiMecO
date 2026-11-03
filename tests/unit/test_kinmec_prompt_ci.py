"""CI-safe tests: prompt reactions in the Cantera mechanism built by ``KiMec``.

The H-group prompt SOP (``tests/unit/data/c4h8_h_group/``: the hot C4H7 PES
read first, then ``H_C4H71-3``, ``H_C4H71-4``, ``2-H_C4H71-3``, so PES 0 is
hot and PES 1, 2, 3 are the PED PESs) gives 12 prompt channels (3 linked
PED pairs x 4 hot species). R1 = ``CH2CHCH2CH3+H`` (PES 1 and 2) and
R2 = ``CH3CHCHCH3+H`` (PES 3); the channels with the same reactant and
product multisets are summed into 8 irreversible ``Mess-data`` reactions
(4 per reactant, two of them with 3 products). The rates follow the real
path: KIN rows -> ``RateCo.load_rates_from_db`` (extended rate tables) ->
``KiMec.prepare_mech`` + ``get_updated_mech`` on a real ``ct.Solution``
(base mechanism ``tests/unit/data/kinmec_prompt/c4h8_h_group_mech.yaml``,
which declares every SOP species), and once through the script rendered by
``SIM.q_up``. No MESS binary, no queue.

KIN rows: one thermal row per ordered species pair of each PES (distinct k
per PES, pair and cell); the channel k of a link is a fixed fraction of its
thermal twin k1 (thermalised 0.6, other well 0.25, ``CH2CHCHCH2+H`` 0.1,
``CH2CH2+CH2CH`` 0.05: sum 1, no channel equal to k1).

Cantera 3.2 reads an equation with H on both sides (``X + H => Y + Z + H``)
as a three-body reaction with collider H: its ``reactants``/``products``
dicts omit H and its equation string is reordered. Reactions are therefore
compared by the species multisets parsed from the equation string, never by
those dicts.
"""
from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Collection
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest
from scipy.constants import Avogadro

from kimeco.kinmec import KiMec
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.writers.prompt_collector import (PromptChannel,
                                             prompt_to_names_by_pes)
from tests.unit.test_mess_c4h8_h_group_ci import (HOT_SPECIES, HOT_WELLS,
                                                  ORDERS4, _assert_clean,
                                                  _read)

MECH = (Path(__file__).resolve().parent / 'data' / 'kinmec_prompt'
        / 'c4h8_h_group_mech.yaml')
#: KIN cm^3 molecule^-1 s^-1 -> Cantera m^3 kmol^-1 s^-1.
FACTOR = Avogadro / 1000
PRES = [1.0]
TEMP = [1000.0, 1500.0]
CELLS = [(p, t) for p in PRES for t in TEMP]
R1, R2 = 'CH2CHCH2CH3+H', 'CH3CHCHCH3+H'
PED_PES = (1, 2, 3)
#: Base reactions of the fixture mechanism, by equation as Cantera writes it.
R0 = 'CH2CHCH2CH3 + H <=> CH2CHCHCH3 + H2'
R1_BASE = 'CH2CH2 + H <=> CH2CH + H2'
R2_BASE = 'CH2CHCH2CH3 + H => CH2CH + CH2CH2 + H2'
R3 = 'CH2CHCHCH3 + H2 => CH2CHCH2CH3 + H'
R4 = 'CH2CHCH2CH3 => CH2CHCHCH2 + H2'

Key = tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]


# ---------------------------------------------------------------------------
# Helpers: settings, KIN rows, RateCo payload, mechanism, reaction keys
# ---------------------------------------------------------------------------
def _settings(prompt: bool = True, use_automech: bool = True,
              **extra: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'postprocess': False, 'rc_pres': list(PRES), 'rc_temp': list(TEMP),
        'pp_pres': [1.0], 'pp_temp': [1500.0],
        'use_automech': use_automech, 'prompt_reactions': prompt}
    settings.update(extra)
    return settings


def _side(names) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(n.strip() for n in names).items()))


def _key(equation: str) -> Key:
    """Reactant and product multisets of a Cantera equation string (H of a
    three-body reaction included)."""
    for arrow in (' <=> ', ' => '):
        if arrow in equation:
            lhs, rhs = equation.split(arrow)
            return _side(lhs.split(' + ')), _side(rhs.split(' + '))
    raise AssertionError(f'no arrow in {equation!r}')


def _key_of(reactants, products) -> Key:
    return _side(reactants), _side(products)


def _label_key(reactant: str, product: str) -> Key:
    """Key of ``reactant => product`` from SOP labels (bimoleculars are
    their fragments joined by ``+``)."""
    return _key_of(reactant.split('+'), product.split('+'))


def _thermal_k(pes_id: int, i: int, j: int, p: float, t: float) -> float:
    """Distinct KIN k per PES, ordered pair (indices in the PES species
    table) and (P, T) value."""
    return 1e-12 * (1 + 0.01 * (16 * pes_id + 4 * i + j)) * (
        1 + t / 1e4 + p / 10)


def _frac(channel: PromptChannel) -> float:
    if channel.thermalised:
        return 0.6
    if channel.hot_species in HOT_WELLS:
        return 0.25
    return {'CH2CHCHCH2+H': 0.1, 'CH2CH2+CH2CH': 0.05}[channel.hot_species]


def _k1(sop: Any, channel: PromptChannel, p: float, t: float) -> float:
    names = sop.species_names_in_pes(channel.ped_pes_id)
    return _thermal_k(channel.ped_pes_id, names.index(channel.ped_reactant),
                      names.index(channel.ped_product), p, t)


def _channel_k(sop: Any, channel: PromptChannel, p: float, t: float,
               zero: Collection[tuple[int, str]] = frozenset()) -> float:
    if (channel.ped_pes_id, channel.kin_row_to_name) in zero:
        return 0.0
    return _frac(channel) * _k1(sop, channel, p, t)


def _thermal_rows(sop: Any, cells=CELLS) -> list[tuple]:
    rows = []
    for pes_id in sop.pes_ids:
        names = sop.species_names_in_pes(pes_id)
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                if i != j:
                    rows += [(p, t, pes_id, a, b,
                              _thermal_k(pes_id, i, j, p, t))
                             for p, t in cells]
    return rows


def _prompt_rows(sop: Any, cells=CELLS,
                 zero: Collection[tuple[int, str]] = frozenset()
                 ) -> list[tuple]:
    """The step-4 KIN layout: (P, T, ped_pes_id, ped_reactant,
    kin_row_to_name, k) per channel and cell."""
    return [(p, t, ch.ped_pes_id, ch.ped_reactant, ch.kin_row_to_name,
             _channel_k(sop, ch, p, t, zero))
            for ch in PromptChannel.fixed_set(sop) for p, t in cells]


def _rateco(sop: Any, rows: list[tuple], prompt: bool,
            pres=PRES, temp=TEMP) -> RateCo:
    """A bare RateCo after ``load_rates_from_db`` on ``rows``."""
    rc = RateCo.__new__(RateCo)
    rc.sop = sop
    rc.pres = list(pres)
    rc.temp = list(temp)
    rc.id = 0
    rc.name = 'G0000E0000'
    rc.prompt_reactions = prompt
    rc.db = cast(Any, SimpleNamespace(
        get_rates_for_kin_id=lambda table, kin_id: list(rows)))
    rc.load_rates_from_db(table='G0000')
    return rc


def _payload(rc: RateCo) -> tuple[dict[int, Any], dict[int, dict[str, int]]]:
    """What ``SIM.q_up`` hands to the SIM script."""
    rates = {int(p): a.tolist() for p, a in rc.rc_by_pes.items()}
    maps = {int(p): dict(m) for p, m in rc.tbl_map_by_pes.items()}
    return rates, maps


def _mech(sop: Any, settings: dict[str, Any], rc: RateCo,
          payload=None) -> tuple[KiMec, Any]:
    """KiMec exactly as the SIM script drives it."""
    km = KiMec(file=str(MECH), settings=settings)
    km.add_SOP(sop)
    km.prepare_mech()
    rates, maps = payload if payload is not None else _payload(rc)
    gas = km.get_updated_mech(rates_by_pes=rates, tbl_map_by_pes=maps)
    return km, gas


def _table(gas: Any) -> dict[Key, list[tuple[bool, tuple[float, ...], Any]]]:
    """{key: [(reversible, forward k at each cell, reaction)]}."""
    ks = []
    for p, t in CELLS:
        gas.TP = t, p * 1e5
        ks.append(np.array(gas.forward_rate_constants))
    out: dict[Key, list] = {}
    for idx, reaction in enumerate(gas.reactions()):
        out.setdefault(_key(reaction.equation), []).append(
            (reaction.reversible, tuple(float(k[idx]) for k in ks), reaction))
    return out


def _signature(gas: Any) -> Counter:
    """Multiset of (key, reversible, k at each cell) of every reaction."""
    return Counter((key, rev, ks) for key, entries in _table(gas).items()
                   for rev, ks, _r in entries)


def _expected_prompt(sop: Any,
                     zero: Collection[tuple[int, str]] = frozenset()
                     ) -> dict[Key, tuple[float, ...]]:
    """Summed prompt k (Cantera units) per prompt equation and cell,
    channels added in fixed-set order."""
    out: dict[Key, list[float]] = {}
    for ch in PromptChannel.fixed_set(sop):
        key = _key_of(ch.ped_reactant.split('+'), ch.product_fragments)
        acc = out.setdefault(key, [0.0] * len(CELLS))
        for idx, (p, t) in enumerate(CELLS):
            acc[idx] += _channel_k(sop, ch, p, t, zero) * FACTOR
    return {key: tuple(v) for key, v in out.items()}


def _linked_pairs(sop: Any) -> list[tuple[int, str, str]]:
    return list(dict.fromkeys(
        (ch.ped_pes_id, ch.ped_reactant, ch.ped_product)
        for ch in PromptChannel.fixed_set(sop)))


def _close(a, b) -> bool:
    return a == pytest.approx(b, rel=1e-12, abs=0.0)


# ---------------------------------------------------------------------------
# Fixtures (the MESS reads are the slow part: once per module)
# ---------------------------------------------------------------------------
@pytest.fixture(scope='module')
def prompt_sop() -> Any:
    sop, _tpls, reader = _read(ORDERS4[0], species=HOT_SPECIES, prompt=True)
    _assert_clean(reader)
    return sop


@pytest.fixture(scope='module')
def plain_sop() -> Any:
    sop, _tpls, reader = _read(ORDERS4[0], species=HOT_SPECIES)
    _assert_clean(reader)
    return sop


@pytest.fixture(scope='module')
def rows(prompt_sop) -> list[tuple]:
    return _thermal_rows(prompt_sop) + _prompt_rows(prompt_sop)


@pytest.fixture(scope='module')
def prompt_mech(prompt_sop, rows) -> tuple[KiMec, Any, RateCo]:
    rc = _rateco(prompt_sop, rows, prompt=True)
    km, gas = _mech(prompt_sop, _settings(), rc)
    return km, gas, rc


@pytest.fixture(scope='module')
def off_mech(prompt_sop, rows) -> tuple[KiMec, Any, RateCo]:
    rc = _rateco(prompt_sop, rows, prompt=False)
    km, gas = _mech(prompt_sop, _settings(prompt=False), rc)
    return km, gas, rc


# ===========================================================================
# Standard cases
# ===========================================================================
def test_payload_layout_on_the_real_sop(prompt_sop, rows) -> None:
    """A0: the SIM payload of a prompt run. Each PED PES table lists its
    species (same indices as prompt off) then its 4 prompt to_names in
    fixed-set order; arrays (1, 2, 8, 8) with each channel's k at
    [ped_reactant, to_name]; every other cell of the added rows/columns 0;
    the thermal block and the hot PES unchanged; int keys, every PES."""
    rc = _rateco(prompt_sop, rows, prompt=True)
    off = _rateco(prompt_sop, rows, prompt=False)
    names_by_pes = prompt_to_names_by_pes(PromptChannel.fixed_set(prompt_sop))
    assert sorted(names_by_pes) == list(PED_PES)
    assert sorted(rc.tbl_map_by_pes) == sorted(rc.rc_by_pes) == [0, 1, 2, 3]
    assert all(type(p) is int for p in rc.tbl_map_by_pes)
    assert rc.tbl_map_by_pes[0] == off.tbl_map_by_pes[0]
    assert np.array_equal(rc.rc_by_pes[0], off.rc_by_pes[0])
    for pes_id in PED_PES:
        species = prompt_sop.species_names_in_pes(pes_id)
        expected = species + names_by_pes[pes_id]
        assert len(names_by_pes[pes_id]) == 4
        tbl = rc.tbl_map_by_pes[pes_id]
        assert list(tbl) == expected
        assert list(tbl.values()) == list(range(8))
        arr = rc.rc_by_pes[pes_id]
        assert arr.shape == (1, 2, 8, 8)
        assert np.array_equal(arr[:, :, :4, :4], off.rc_by_pes[pes_id])
        set_cells = np.zeros(arr.shape, dtype=bool)
        for ch in PromptChannel.fixed_set(prompt_sop):
            if ch.ped_pes_id != pes_id:
                continue
            i, j = tbl[ch.ped_reactant], tbl[ch.kin_row_to_name]
            set_cells[:, :, i, j] = True
            for ip, p in enumerate(PRES):
                for it, t in enumerate(TEMP):
                    assert arr[ip, it, i, j] == _channel_k(
                        prompt_sop, ch, p, t)
        added = np.zeros(arr.shape, dtype=bool)
        added[:, :, 4:, :] = True
        added[:, :, :, 4:] = True
        assert not arr[added & ~set_cells].any()


def test_prompt_reactions_present_including_three_products(
        prompt_mech, prompt_sop) -> None:
    """A1: each of the 8 prompt equations occurs exactly once, irreversible,
    ``Mess-data`` on the active grid; the 4 three-product ones (two per
    reactant) are among them; KiMec merged 12 channels into 8 reactions
    (2 channels each for R1, 1 for R2)."""
    km, gas, _rc = prompt_mech
    expected = _expected_prompt(prompt_sop)
    assert len(expected) == 8
    table = _table(gas)
    three = [key for key in expected if sum(n for _s, n in key[1]) == 3]
    assert len(three) == 4
    for key in expected:
        assert len(table[key]) == 1, key
        reversible, _ks, reaction = table[key][0]
        assert reversible is False
        assert reaction.reaction_type.endswith('Mess-data')
        assert reaction.input_data['Pgrid'] == [1e5]
        assert reaction.input_data['Tgrid'] == TEMP
    assert len(km.merged_prompt_reactions) == 8
    counts = Counter((m.reactants, len(m.channels))
                     for m in km.merged_prompt_reactions)
    assert counts == {(('CH2CHCH2CH3', 'H'), 2): 4,
                      (('CH3CHCHCH3', 'H'), 1): 4}
    assert sum(len(m.channels) for m in km.merged_prompt_reactions) == 12


def test_same_equation_channels_are_summed(prompt_mech, prompt_sop) -> None:
    """A2: at every cell each prompt reaction's k is the sum of its channels
    (PES 1 and PES 2 for R1, products in either order) x Avogadro/1000."""
    _km, gas, _rc = prompt_mech
    table = _table(gas)
    for key, ks in _expected_prompt(prompt_sop).items():
        assert _close(table[key][0][1], ks), key
    # The thermalised channel of PES 1 and the isomer channel of PES 2.
    key = _key_of(['CH2CHCH2CH3', 'H'], ['CH2CHCHCH3', 'H2'])
    chans = [ch for ch in PromptChannel.fixed_set(prompt_sop)
             if _key_of(ch.ped_reactant.split('+'), ch.product_fragments)
             == key]
    assert [(ch.ped_pes_id, ch.kin_row_to_name) for ch in chans] == [
        (1, 'CH2CHCHCH3+H2__prompt'), (2, 'H2+CH2CHCHCH3__prompt')]
    assert _close(table[key][0][1], tuple(
        (0.6 * _k1(prompt_sop, chans[0], p, t)
         + 0.25 * _k1(prompt_sop, chans[1], p, t)) * FACTOR
        for p, t in CELLS))


def test_no_duplicate_thermal_abstraction(prompt_mech, off_mech,
                                          prompt_sop) -> None:
    """A3: for each linked PED pair R => P one reaction only, with the
    summed prompt k, not the thermal k1 x factor: the thermal forward is
    gone (it is there, once, with k1, when prompt mode is off)."""
    expected = _expected_prompt(prompt_sop)
    table = _table(prompt_mech[1])
    off = _table(off_mech[1])
    for pes_id, reactant, product in _linked_pairs(prompt_sop):
        key = _label_key(reactant, product)
        assert len(table[key]) == 1, key
        names = prompt_sop.species_names_in_pes(pes_id)
        i, j = names.index(reactant), names.index(product)
        k1 = tuple(_thermal_k(pes_id, i, j, p, t) * FACTOR
                   for p, t in CELLS)
        assert _close(table[key][0][1], expected[key])
        assert table[key][0][1] != pytest.approx(k1, rel=1e-6)
        assert [ks for _rev, ks, _r in off[key]] == [pytest.approx(k1)]


def test_mess_reverse_kept_unchanged(prompt_mech, off_mech,
                                     prompt_sop) -> None:
    """A4: each PED PES keeps exactly one P => R, irreversible, with the KIN
    P -> R row x factor, identical to the prompt-off mechanism, never merged
    with a prompt reaction."""
    table = _table(prompt_mech[1])
    off = _table(off_mech[1])
    prompt_keys = set(_expected_prompt(prompt_sop))
    for pes_id, reactant, product in _linked_pairs(prompt_sop):
        key = _label_key(product, reactant)
        assert key not in prompt_keys
        assert len(table[key]) == 1, key
        reversible, ks, reaction = table[key][0]
        assert reversible is False
        assert reaction.reaction_type == 'Mess-data'
        names = prompt_sop.species_names_in_pes(pes_id)
        i, j = names.index(product), names.index(reactant)
        assert _close(ks, tuple(_thermal_k(pes_id, i, j, p, t) * FACTOR
                                for p, t in CELLS))
        assert [e[:2] for e in off[key]] == [(reversible, ks)]


def test_total_k1_conserved(prompt_mech, off_mech, prompt_sop) -> None:
    """A5: per PED reactant and cell, the sum of its prompt reactions'
    Cantera k = the sum of its channels (the prompt-rates values) x factor
    = the sum of its thermal forwards to non-fake-well products in the
    prompt-off mechanism (the fractions sum to 1): KiMec loses or
    duplicates nothing."""
    table = _table(prompt_mech[1])
    off = _table(off_mech[1])
    channels = PromptChannel.fixed_set(prompt_sop)
    for reactant in (R1, R2):
        lhs = _side(reactant.split('+'))
        prompt_keys = {_key_of(ch.ped_reactant.split('+'),
                               ch.product_fragments)
                       for ch in channels if ch.ped_reactant == reactant}
        for idx, (p, t) in enumerate(CELLS):
            total = sum(table[key][0][1][idx] for key in prompt_keys)
            json_total = sum(_channel_k(prompt_sop, ch, p, t)
                             for ch in channels
                             if ch.ped_reactant == reactant) * FACTOR
            thermal = sum(
                ks[idx] for key, entries in off.items() if key[0] == lhs
                for _rev, ks, reaction in entries
                if reaction.reaction_type == 'Mess-data'
                and not any(n.startswith('FakeW-') for n, _c in key[1]))
            assert total == pytest.approx(json_total, rel=1e-12)
            assert total == pytest.approx(thermal, rel=1e-12)


def test_everything_else_unchanged(prompt_mech, off_mech,
                                   prompt_sop) -> None:
    """A6: removing the 8 prompt reactions from the prompt mechanism and,
    from the prompt-off one, the 3 thermal forwards and the base reaction r2
    (replaced by a prompt reaction) leaves the same reactions, reversibility
    and rates: fake-well reactions of the PED PESs, every hot-PES reaction,
    the 3 reverses, base r1 and base r4 (kept in both modes, see A7)."""
    prompt_keys = set(_expected_prompt(prompt_sop))
    forwards = {_label_key(r, p) for _pes, r, p in _linked_pairs(prompt_sop)}
    sig_on = _signature(prompt_mech[1])
    sig_off = _signature(off_mech[1])
    rest_on = Counter({e: n for e, n in sig_on.items()
                       if e[0] not in prompt_keys})
    rest_off = Counter({e: n for e, n in sig_off.items()
                        if e[0] not in prompt_keys | forwards})
    assert rest_on == rest_off
    assert sum(1 for e in rest_on if e[0] == _key(R4)) == 1
    assert sum(sig_on.values()) == sum(sig_off.values()) - 3 - 1 + 8


def test_base_reactions_replaced_once(prompt_mech, off_mech) -> None:
    """A7: r0 and r3 (thermal forward / MESS reverse of PES 1) are removed
    in both modes; r2, whose species only a 3-product prompt reaction has,
    only in prompt mode (the placeholders of prepare_mech include the
    prompt reactions); r1 stays once in both modes.

    r4 ``CH2CHCH2CH3 => CH2CHCHCH2 + H2`` is no reaction of the SOP and
    stays in both modes. Regression: Cantera reads the prompt reaction
    ``CH2CHCH2CH3 + H => H2 + CH2CHCHCH2 + H`` as three-body (collider H),
    so its reactants/products dicts equal r4's; ``find_redundant_idx`` once
    matched them and removed r4 in prompt mode. It now matches a prompt
    reaction with its collider included, so r4 is kept."""
    on = [r.equation for r in prompt_mech[0].reactions]
    off = [r.equation for r in off_mech[0].reactions]
    assert on == [R1_BASE, R4]
    assert off == [R1_BASE, R2_BASE, R4]
    three_body = [r for r in prompt_mech[1].reactions()
                  if r.reaction_type == 'three-body-Mess-data']
    assert sorted(r.equation for r in three_body) == [
        'CH2CHCH2CH3 + H => CH2CHCHCH2 + H2 + H',
        'CH3CHCHCH3 + H => CH2CHCHCH2 + H2 + H']
    r4 = next(r for r in off_mech[1].reactions() if r.equation == R4)
    match = next(r for r in three_body if r.equation.startswith('CH2CHCH2'))
    assert (match.reactants, match.products) == (r4.reactants, r4.products)


# ===========================================================================
# Edge cases
# ===========================================================================
def test_find_redundant_idx_removes_each_base_reaction_once() -> None:
    """A8 regression: two new reactions matching the same base reaction X
    of [X, Y, Z]: find_redundant_idx gives X's index once, and prepare_mech
    removes X only (before the fix the index came twice and Y was popped
    too)."""
    import cantera
    ct: Any = cantera
    base = ct.Solution(str(MECH))
    x, y, z = base.reactions()[1:4]
    km = KiMec.__new__(KiMec)
    km.reactions = [x, y, z]
    km.SOP = cast(Any, SimpleNamespace(pes_ids=[]))
    km.pres, km.temp = list(PRES), list(TEMP)
    km.add_species = lambda: None
    km.create_reactions_templates = lambda: None
    twins = [ct.Reaction.from_yaml(
        f'equation: {x.equation}\n'
        'rate-constant: {A: 1.0, b: 0.0, Ea: 0.0}', base) for _ in range(2)]
    km.create_reactions = lambda rates_by_pes, tbl_map_by_pes: twins
    assert km.find_redundant_idx(twins) == [0]
    km.prepare_mech()
    assert [r.equation for r in km.reactions] == [y.equation, z.equation]


# find_redundant_idx keys (A9-A12): new reactions built from KiMecO's own
# Mess-data template on a small inline mechanism (shared dummy thermo, never
# used: only the species dicts and collider matter).
_KEYS_MECH = """
phases:
- name: gas
  thermo: ideal-gas
  elements: [C, H, O, Ar]
  species: [AR, H, H2, O2, HO2, CH2CHCH2CH3, CH2CHCHCH2]
  kinetics: gas
species:
- name: AR
  composition: {Ar: 1}
  thermo: &thermo
    model: NASA7
    temperature-ranges: [200.0, 1000.0, 6000.0]
    data:
    - [2.5, 0.0, 0.0, 0.0, 0.0, -745.375, 4.366]
    - [2.5, 0.0, 0.0, 0.0, 0.0, -745.375, 4.366]
- {name: H, composition: {H: 1}, thermo: *thermo}
- {name: H2, composition: {H: 2}, thermo: *thermo}
- {name: O2, composition: {O: 2}, thermo: *thermo}
- {name: HO2, composition: {H: 1, O: 2}, thermo: *thermo}
- {name: CH2CHCH2CH3, composition: {C: 4, H: 8}, thermo: *thermo}
- {name: CH2CHCHCH2, composition: {C: 4, H: 6}, thermo: *thermo}
reactions: []
"""
#: A prompt reaction with three products, H on both sides (as R1 gives).
_PROMPT_EQ = 'CH2CHCH2CH3 + H => H2 + CH2CHCHCH2 + H'


@pytest.fixture(scope='module')
def keys_gas() -> Any:
    import cantera
    ct: Any = cantera
    return ct.Solution(yaml=_KEYS_MECH)


def _keys_km(base: list[Any]) -> KiMec:
    """A KiMec holding only ``base`` as base reactions and the active grid."""
    km = KiMec.__new__(KiMec)
    km.pres, km.temp = list(PRES), list(TEMP)
    km.rc_tpl = km._build_rc_tpl()
    km.reactions = list(base)
    return km


def _base_reac(gas: Any, equation: str, extra: str = '') -> Any:
    """A base (mechanism) reaction with an Arrhenius rate."""
    import cantera
    ct: Any = cantera
    return ct.Reaction.from_yaml(
        f'equation: {equation}\n{extra}'
        'rate-constant: {A: 1.0, b: 0.0, Ea: 0.0}', gas)


def _mess_reac(gas: Any, equation: str) -> Any:
    """A new reaction from KiMec's own Mess-data template, zero rates."""
    import cantera
    ct: Any = cantera
    km = _keys_km([])
    return ct.Reaction.from_yaml(km._reaction_template(equation).format(
        rates=np.zeros((len(PRES), len(TEMP)))), gas)


def test_find_redundant_idx_thermal_ignores_collider(keys_gas) -> None:
    """A9: a thermal MESS ``H + O2 => HO2`` replaces the base three-body
    ``H + O2 + AR <=> HO2 + AR`` (collider left out, HEAD rule of non-prompt
    runs), passed alone or with an explicit empty prompt list."""
    base = _base_reac(keys_gas, 'H + O2 + AR <=> HO2 + AR')
    assert base.reaction_type == 'three-body-Arrhenius'
    km = _keys_km([base])
    new = [_mess_reac(keys_gas, 'H + O2 => HO2')]
    assert km.find_redundant_idx(new) == [0]
    assert km.find_redundant_idx(new, prompt_reactions=()) == [0]


def test_find_redundant_idx_prompt_keeps_collider(keys_gas) -> None:
    """A10 regression: the prompt ``X + H => H2 + Y + H``, which Cantera reads
    as three-body with collider H (dicts equal to those of ``X => Y + H2``),
    does not replace the base ``X => Y + H2``."""
    prompt = _mess_reac(keys_gas, _PROMPT_EQ)
    base = _base_reac(keys_gas, R4)
    assert prompt.reaction_type == 'three-body-Mess-data'
    assert (prompt.reactants, prompt.products) == (base.reactants,
                                                    base.products)
    km = _keys_km([base])
    assert km.find_redundant_idx([], prompt_reactions=[prompt]) == []


@pytest.mark.parametrize('arrow, extra, reaction_type', [
    ('=>', '', 'three-body-Arrhenius'),
    ('=>', 'type: elementary\n', 'Arrhenius'),
    ('<=>', '', 'three-body-Arrhenius')],
    ids=['three_body', 'elementary', 'three_body_reversible'])
def test_find_redundant_idx_prompt_replaces_same_equation(
        keys_gas, arrow, extra, reaction_type) -> None:
    """A11: the prompt reaction replaces a base reaction with the same full
    equation (H on both sides), read as three-body or as elementary,
    reversible or not; neither ``X => Y + H2`` nor a three-body reaction of
    other species is touched."""
    same = _base_reac(keys_gas, _PROMPT_EQ.replace('=>', arrow), extra)
    assert same.reaction_type == reaction_type
    km = _keys_km([_base_reac(keys_gas, R4), same,
                   _base_reac(keys_gas, 'H + O2 + AR <=> HO2 + AR')])
    prompt = _mess_reac(keys_gas, _PROMPT_EQ)
    assert km.find_redundant_idx([], prompt_reactions=[prompt]) == [1]


def test_find_redundant_idx_one_argument_is_all_thermal(keys_gas) -> None:
    """A12: the one-argument call matches every new reaction with the
    thermal key: the 3-product reaction then replaces ``X => Y + H2`` (equal
    Cantera dicts), not the same equation read as elementary; passed as a
    prompt reaction it gives the reverse."""
    prompt = _mess_reac(keys_gas, _PROMPT_EQ)
    km = _keys_km([_base_reac(keys_gas, R4),
                   _base_reac(keys_gas, _PROMPT_EQ, 'type: elementary\n')])
    assert km.find_redundant_idx([prompt]) == [0]
    assert km.find_redundant_idx([], prompt_reactions=[prompt]) == [1]


@pytest.mark.parametrize('settings', [
    _settings(prompt=False),
    _settings(prompt=True, use_automech=False)],
    ids=['prompt_off', 'no_automech'])
def test_prompt_off_mechanism_unchanged(prompt_sop, plain_sop, rows,
                                        settings) -> None:
    """A9 (a, b): outside prompt mode (prompt_reactions off, or no
    automech) the prompt SOP and rows with prompt rows give the same
    mechanism (equations, reversibility, rates at every cell) as the
    non-prompt SOP with thermal rows only."""
    from kimeco.writers.prompt_collector import is_prompt_run
    assert is_prompt_run(settings) is False
    rc = _rateco(prompt_sop, rows, prompt=False)
    km, gas = _mech(prompt_sop, settings, rc)
    # getattr: this pin holds on the pre-prompt KiMec too (no attribute).
    assert getattr(km, 'merged_prompt_reactions', ()) == ()
    ref_rc = _rateco(plain_sop, _thermal_rows(plain_sop), prompt=False)
    _ref_km, ref = _mech(plain_sop, _settings(prompt=False), ref_rc)
    assert _signature(gas) == _signature(ref)


def test_prompt_off_equations_match_an_independent_derivation(
        off_mech, prompt_sop) -> None:
    """A9 (c): the prompt-off equation multiset equals the four thermal
    groups derived here (well->well and bimolecular->bimolecular without
    identity, well->bimolecular, bimolecular->well, per PES, names of
    species_names_in_pes) plus the surviving base reactions r1, r2, r4:
    pins today's mechanism independently of the new code."""
    from kimeco.well import Well

    def _names(item):
        return [item.name] if isinstance(item, Well) else [
            f.name for f in item.fragments]

    expected: Counter = Counter()
    for pes_id in prompt_sop.pes_ids:
        items = prompt_sop.wells_in(pes_id) + prompt_sop.bimols_in(pes_id)
        names = set(prompt_sop.species_names_in_pes(pes_id))
        for a in items:
            for b in items:
                if a is not b and a.name in names and b.name in names:
                    expected[_key_of(_names(a), _names(b))] += 1
    for equation in (R1_BASE, R2_BASE, R4):
        expected[_key(equation)] += 1
    got = Counter(_key(r.equation) for r in off_mech[1].reactions())
    assert got == expected


def test_all_zero_channels_become_reactions(prompt_sop) -> None:
    """A10: zero channels are kept, not dropped. R2's 3-product channel all
    0: its reaction exists with k 0; R1's 3-product channels H2+CH2CH2+CH2CH
    both 0: the reaction exists with k 0 and still replaces base r2; R1's
    isomer channel of PES 2 0: the summed reaction equals the PES 1
    thermalised channel alone."""
    zero = {(3, 'H2+CH2CH2+CH2CH__prompt'), (1, 'H2+CH2CH2+CH2CH__prompt'),
            (2, 'H2+CH2CH2+CH2CH__prompt'), (2, 'H2+CH2CHCHCH3__prompt')}
    rows = _thermal_rows(prompt_sop) + _prompt_rows(prompt_sop, zero=zero)
    rc = _rateco(prompt_sop, rows, prompt=True)
    km, gas = _mech(prompt_sop, _settings(), rc)
    table = _table(gas)
    expected = _expected_prompt(prompt_sop, zero=zero)
    assert len(expected) == 8
    for key, ks in expected.items():
        assert len(table[key]) == 1
        assert _close(table[key][0][1], ks)
    for reactant in (['CH3CHCHCH3', 'H'], ['CH2CHCH2CH3', 'H']):
        key = _key_of(reactant, ['H2', 'CH2CH2', 'CH2CH'])
        assert table[key][0][1] == (0.0, 0.0)
    assert R2_BASE not in [r.equation for r in km.reactions]
    therm = next(ch for ch in PromptChannel.fixed_set(prompt_sop)
                 if ch.ped_pes_id == 1 and ch.thermalised)
    key = _key_of(['CH2CHCH2CH3', 'H'], ['CH2CHCHCH3', 'H2'])
    assert _close(table[key][0][1], tuple(
        0.6 * _k1(prompt_sop, therm, p, t) * FACTOR for p, t in CELLS))


def test_grid_switch_rebuilds_prompt_reactions(prompt_sop) -> None:
    """A11: templates built on the rc grid (1 P x 2 T), rates on the pp grid
    (1 P x 1 T): get_updated_mech switches to the pp grid and rebuilds the
    prompt reactions on it (Pgrid/Tgrid), which evaluate at the pp T."""
    pp_cells = [(1.0, 1500.0)]
    rows = (_thermal_rows(prompt_sop, CELLS)
            + _prompt_rows(prompt_sop, CELLS))
    rc = _rateco(prompt_sop, rows, prompt=True, pres=[1.0], temp=[1500.0])
    km = KiMec(file=str(MECH), settings=_settings())
    km.add_SOP(prompt_sop)
    km.prepare_mech()
    assert km.temp == TEMP
    gas = km.get_updated_mech(*_payload(rc))
    assert (km.pres, km.temp) == ([1.0], [1500.0])
    for tpl in km.merged_prompt_tpls.values():
        assert '1500.0 K' in tpl and '1000.0 K' not in tpl
    gas.TP = 1500.0, 1e5
    ks = gas.forward_rate_constants
    by_key = {_key(r.equation): (idx, r) for idx, r in
              enumerate(gas.reactions())}
    for ch_key, _ks in _expected_prompt(prompt_sop).items():
        idx, reaction = by_key[ch_key]
        assert reaction.input_data['Tgrid'] == [1500.0]
        expected = sum(
            _channel_k(prompt_sop, ch, *pp_cells[0]) * FACTOR
            for ch in PromptChannel.fixed_set(prompt_sop)
            if _key_of(ch.ped_reactant.split('+'), ch.product_fragments)
            == ch_key)
        assert ks[idx] == pytest.approx(expected, rel=1e-12)


def test_prompt_off_without_pes_file_data_or_prompt_keys(plain_sop) -> None:
    """A12 (b): a SOP without ``pes_file_data`` and settings without the
    ``use_automech``/``prompt_reactions`` keys build the same prompt-off
    mechanism (the prompt gate never reads them)."""
    sop = deepcopy(plain_sop)
    del sop.pes_file_data
    assert not hasattr(sop, 'pes_file_data')
    settings = _settings()
    del settings['use_automech'], settings['prompt_reactions']
    rc = _rateco(sop, _thermal_rows(sop), prompt=False)
    _km, gas = _mech(sop, settings, rc)
    ref_rc = _rateco(plain_sop, _thermal_rows(plain_sop), prompt=False)
    _ref_km, ref = _mech(plain_sop, _settings(prompt=False), ref_rc)
    assert _signature(gas) == _signature(ref)


def test_prompt_mode_payload_without_prompt_names_raises(prompt_sop,
                                                         rows) -> None:
    """A13: prompt mode with thermal-only tables (no prompt to_names) stops
    with ValueError naming the PES and the missing name, never a silent
    loss of the forward k1."""
    rc = _rateco(prompt_sop, rows, prompt=False)
    km = KiMec(file=str(MECH), settings=_settings())
    km.add_SOP(prompt_sop)
    km.prepare_mech()
    with pytest.raises(ValueError,
                       match=r'rate table of PES 1 has no '
                             r'H2\+CH2CH2\+CH2CH__prompt'):
        km.get_updated_mech(*_payload(rc))


# ===========================================================================
# SIM template round trip
# ===========================================================================
class _NoQueue:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    def add_to_q(self, **kwargs: Any) -> None:
        self.added.append(kwargs)

    def status(self, id: int, jtype: str) -> Any:
        return None


def test_sim_script_round_trip(tmp_path, prompt_mech, prompt_sop) -> None:
    """F1: SIM.q_up renders the extended payload into the SIM script; read
    back (``ast.literal_eval``) and fed to a fresh KiMec as the script
    does, it gives the same mechanism as the payload itself; the rendered
    tables carry 4 prompt to_names under each PED PES (12)."""
    _km, gas, rc = prompt_mech
    (tmp_path / '00').mkdir()
    exp = SimpleNamespace(
        data=np.array([[0.0, 1e-3]]), species=['H'], new_tpl=True,
        tpl_idx=0, sim_file=('tbl_map_by_pes = {tbl_map_by_pes}\n'
                             'rates_by_pes = {rates_by_pes}\n'))
    settings = {'experiments': [exp], 'cpu_sim': 1, 'mem_sim': 100,
                'scratch_base': str(tmp_path) + '/scratch/',
                'project_name': 'KMO_Project',
                'init_loc': str(tmp_path) + '/',
                'input_file': str(tmp_path / 'input.json')}
    queue = _NoQueue()
    sim = SIM(sop=prompt_sop, kin=rc, id=3, q_idx=0, gen_name='G0000',
              db=cast(Any, None), loc=str(tmp_path), q_sys=cast(Any, queue),
              set=settings, klog=cast(Any, None))
    sim.q_up()
    assert len(queue.added) == 1
    script = (tmp_path / '00' / 'G0000E0003S_exp00.py').read_text()
    values = {}
    for line in script.splitlines():
        name, _eq, literal = line.partition(' = ')
        values[name] = ast.literal_eval(literal)
    maps, rates = values['tbl_map_by_pes'], values['rates_by_pes']
    assert maps == rc.tbl_map_by_pes
    prompt_names = [n for p in PED_PES for n in maps[p]
                    if n.endswith('__prompt')]
    assert len(prompt_names) == 12
    assert not [n for n in maps[0] if n.endswith('__prompt')]
    _km2, gas2 = _mech(prompt_sop, _settings(), rc, payload=(rates, maps))
    assert _signature(gas2) == _signature(gas)
