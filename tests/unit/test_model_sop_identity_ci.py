from __future__ import annotations

from kimeco.enums import ModelStatus
from kimeco.model import Model
from kimeco.parameters import SOP


def _make_sop(factor: float = 1.0,
              power: float = 2.0,
              n_exp: int = 1) -> SOP:
    """Build a minimal SOP whose ``parameters_names`` is well defined."""
    sop = SOP(n_exp=n_exp)
    sop.factor = factor
    sop.power = power
    sop.pres = [1.0]
    sop.temp = [300.0]
    return sop


# ---------------------------------------------------------------------------
# SOP identity
# ---------------------------------------------------------------------------
def test_sop_eq_hash_and_notimplemented() -> None:
    """SOP equality/hash follow the parameter values (score included); comparing
    with None or a non-SOP returns NotImplemented."""
    # -- test_sop_eq_and_hash_true_when_parameters_names_equal
    a = _make_sop()
    b = _make_sop()

    assert a == b
    assert hash(a) == hash(b)

    # -- test_sop_eq_false_when_score_differs
    a = _make_sop()
    b = _make_sop()
    # Scores participate in parameters_names, so mutating one breaks equality.
    key = next(iter(b.scores))
    b.scores[key] = 0.5

    assert a != b
    assert hash(a) != hash(b)

    # -- test_sop_eq_notimplemented_for_none_and_non_sop
    a = _make_sop()

    assert a.__eq__(None) is NotImplemented
    assert a.__eq__(object()) is NotImplemented
    # Python falls back to identity, so no exception is raised.
    assert (a == None) is False  # noqa: E711
    assert a != None  # noqa: E711


# ---------------------------------------------------------------------------
# Model identity
# ---------------------------------------------------------------------------
def test_model_eq_hash_and_notimplemented() -> None:
    """Model equality covers SOP, status, id and gen; the hash excludes status;
    None or a non-Model returns NotImplemented."""
    # -- test_model_eq_true_when_all_match
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0)

    assert m1 == m2
    assert hash(m1) == hash(m2)

    # -- test_model_eq_false_on_status_but_hash_excludes_status
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0,
               status=ModelStatus.KIN.value)

    # __eq__ includes status ...
    assert m1 != m2
    # ... but __hash__ deliberately excludes it.
    assert hash(m1) == hash(m2)

    # -- test_model_eq_false_on_id_or_gen
    base = Model(sop=_make_sop(), id=0, gen=0)

    assert base != Model(sop=_make_sop(), id=1, gen=0)
    assert base != Model(sop=_make_sop(), id=0, gen=1)

    # -- test_model_eq_notimplemented_for_none_and_non_model
    m1 = Model(sop=_make_sop(), id=0, gen=0)

    assert m1.__eq__(None) is NotImplemented
    assert m1.__eq__(5) is NotImplemented
    assert (m1 == None) is False  # noqa: E711


def test_set_deduplication_of_models() -> None:
    """A set collapses identical models, keeps models differing by status or
    SOP, and ignores the origin prefix."""
    # -- test_set_collapses_identical_models
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0)

    assert len({m1, m2}) == 1

    # -- test_set_preserves_status_differing_models
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0,
               status=ModelStatus.KIN.value)

    # Same hash bucket, but __eq__ keeps them distinct.
    assert len({m1, m2}) == 2

    # -- test_set_preserves_sop_differing_models
    m1 = Model(sop=_make_sop(factor=1.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=9.0), id=0, gen=0)

    assert len({m1, m2}) == 2

    # -- test_set_dedup_ignores_origin_prefix
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0)
    m1.origin_prefix = 'G'
    m2.origin_prefix = 'NM'

    # origin_prefix participates in neither __eq__ nor __hash__.
    assert m1 == m2
    assert len({m1, m2}) == 1


# ---------------------------------------------------------------------------
# Model.different_parameters
# ---------------------------------------------------------------------------
def test_different_parameters_counts() -> None:
    """different_parameters counts 0 for identical models, 1 or many physical
    differences, is symmetric and excludes the score key."""
    # -- test_different_parameters_identical_models_returns_zero
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0)

    assert m1.different_parameters(m2) == 0

    # -- test_different_parameters_single_physical_diff_returns_one
    m1 = Model(sop=_make_sop(factor=1.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=9.0), id=0, gen=0)

    # Only the ETF/'fact' parameter differs.
    assert m1.different_parameters(m2) == 1

    # -- test_different_parameters_multiple_diffs_returns_correct_count
    m1 = Model(sop=_make_sop(factor=1.0, power=2.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=9.0, power=5.0), id=0, gen=0)

    # Both 'fact' and 'pow' differ.
    assert m1.different_parameters(m2) == 2

    # -- test_different_parameters_is_symmetric
    m1 = Model(sop=_make_sop(factor=1.0, power=2.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=9.0, power=5.0), id=0, gen=0)

    assert m1.different_parameters(m2) == m2.different_parameters(m1)

    # -- test_different_parameters_score_key_excluded_returns_zero
    m1 = Model(sop=_make_sop(), id=0, gen=0)
    m2 = Model(sop=_make_sop(), id=0, gen=0)
    # Mutate only a score entry; 'score' keys are excluded from the count.
    key = next(iter(m2.sop.scores))
    m2.sop.scores[key] = 0.5

    assert m1.different_parameters(m2) == 0


def test_different_parameters_tolerances() -> None:
    """Differences below rtol are not counted, above rtol are; near zero the
    default atol applies."""
    # -- test_different_parameters_diff_below_rtol_not_counted
    m1 = Model(sop=_make_sop(factor=1.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=1.0 + 5e-7), id=0, gen=0)

    # Relative diff (~5e-7) is below rtol=1e-6, so it is treated as close.
    assert m1.different_parameters(m2) == 0

    # -- test_different_parameters_diff_above_rtol_counted
    m1 = Model(sop=_make_sop(factor=1.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=1.0 + 2e-6), id=0, gen=0)

    # Relative diff (~2e-6) exceeds rtol=1e-6, so it counts as different.
    assert m1.different_parameters(m2) == 1

    # -- test_different_parameters_near_zero_uses_default_atol
    m1 = Model(sop=_make_sop(factor=0.0), id=0, gen=0)
    m2 = Model(sop=_make_sop(factor=1e-9), id=0, gen=0)

    # Near zero, np.isclose's default atol=1e-8 absorbs the 1e-9 gap.
    assert m1.different_parameters(m2) == 0


