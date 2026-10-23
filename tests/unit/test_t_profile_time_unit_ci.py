from __future__ import annotations

import numpy as np

from kimeco.experiments.t_profile import TimeProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_csv(tmp_path, name, header, rows):
    """Write a small CSV file and return its path."""
    path = tmp_path / name
    lines = [','.join(header)]
    for row in rows:
        lines.append(','.join(str(v) for v in row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


def _make_time_profile(species, data, time_unit='s'):
    """Build a minimal TimeProfile without touching KMOLogger behaviour."""
    return TimeProfile(
        temp=500.0,
        pres=101325.0,
        composition={'O2': 1.0},
        data_file='data.csv',
        error_file='error.csv',
        sim_file='sim.inp',
        settings={},
        klog=None,          # type: ignore[arg-type]  # stored, never called
        species=species,
        data=np.asarray(data, dtype=float),
        error=np.zeros_like(np.asarray(data, dtype=float)),
        time_unit=time_unit,
    )


def _expect_raises(failures, label, exc_type, func, *args):
    """Record a failure unless ``func(*args)`` raises ``exc_type``."""
    try:
        func(*args)
    except exc_type:
        return
    except Exception as exc:  # wrong exception type
        failures.append(f'{label}: raised {type(exc).__name__}, '
                        f'expected {exc_type.__name__}')
        return
    failures.append(f'{label}: no {exc_type.__name__} raised')


# ---------------------------------------------------------------------------
# 1) Valid header parsing + seconds normalization via read_data
# ---------------------------------------------------------------------------
_VALID_HEADERS = (
    ('time', 's', 1.0),
    ('time[s]', 's', 1.0),
    ('TIME [ms]', 'ms', 1e-3),
    ('time[milliseconds]', 'milliseconds', 1e-3),
    ('time[millisecond]', 'millisecond', 1e-3),
    ('time[1e-3s]', '1e-3s', 1e-3),
    ('time[0.001 s]', '0.001 s', 1e-3),
    ('time[1E-3s]', '1E-3s', 1e-3),
    ('time[1e-3]', '1e-3', 1e-3),
    ('time[min]', 'min', 60.0),
    ('time[us]', 'us', 1e-6),
)


def test_read_data_valid_headers_scale_time_to_seconds(tmp_path):
    """header[0] is normalised to 'time', species headers untouched, the raw
    bracket content is kept as time_unit, only the time row is converted to
    seconds. A plain 'time' header stays backward compatible."""
    raw_time = [1.0, 2.0, 3.0]
    sp_a = [10.0, 20.0, 30.0]
    sp_b = [0.5, 0.6, 0.7]
    rows = list(zip(raw_time, sp_a, sp_b))
    failures = []
    for idx, (header, expected_unit, factor) in enumerate(_VALID_HEADERS):
        file = _write_csv(tmp_path, f'data{idx}.csv', [header, 'A', 'B'], rows)
        headers, matrix, time_unit = TimeProfile.read_data(file)
        if headers != ['time', 'A', 'B']:
            failures.append(f'{header!r}: headers {headers}')
        if time_unit != expected_unit:
            failures.append(f'{header!r}: unit {time_unit!r} != {expected_unit!r}')
        if not np.allclose(matrix[0], np.array(raw_time) * factor):
            failures.append(f'{header!r}: time row {matrix[0]}')
        if not (np.allclose(matrix[1], sp_a) and np.allclose(matrix[2], sp_b)):
            failures.append(f'{header!r}: species rows scaled')
    assert not failures, '\n'.join(failures)

    # Backward compatibility: plain 'time' header.
    file = _write_csv(tmp_path, 'plain.csv', ['time', 'A'],
                      [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)])
    headers, matrix, time_unit = TimeProfile.read_data(file)
    assert headers == ['time', 'A']
    assert time_unit == 's'
    np.testing.assert_allclose(matrix[0], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(matrix[1], [1.0, 2.0, 3.0])


def test_parse_time_header_and_unit_to_seconds():
    """Whitespace/case tolerance of ``_parse_time_header``, a factor-only
    bracket, and the ``_unit_to_seconds`` table."""
    failures = []
    for header, expected_is_time, expected_unit, expected_factor in (
            ('time', True, 's', 1.0),
            ('  time  ', True, 's', 1.0),
            ('Time', True, 's', 1.0),
            ('TIME', True, 's', 1.0),
            ('time[ ms ]', True, 'ms', 1e-3),
            ('TIME [ MS ]', True, 'MS', 1e-3),
            ('time[  1e-3  s ]', True, '1e-3  s', 1e-3),
            ('time[0.001 s]', True, '0.001 s', 1e-3),
            ('time[min]', True, 'min', 60.0),
            ('time[us]', True, 'us', 1e-6),
            ('foo', False, 's', 1.0),
            ('time[1e-3]', True, '1e-3', 1e-3)):
        got = TimeProfile._parse_time_header(header)
        if (got[0] is not expected_is_time or got[1] != expected_unit
                or not np.isclose(got[2], expected_factor)):
            failures.append(f'{header!r}: {got}, expected '
                            f'{(expected_is_time, expected_unit, expected_factor)}')
    for unit, expected in (('ms', 1e-3), ('millisecond', 1e-3), ('s', 1.0),
                           ('min', 60.0), ('us', 1e-6)):
        got = TimeProfile._unit_to_seconds(unit)
        if not np.isclose(got, expected):
            failures.append(f'_unit_to_seconds({unit!r}) = {got}, expected {expected}')
    assert not failures, '\n'.join(failures)


# ---------------------------------------------------------------------------
# 2) Invalid / error paths
# ---------------------------------------------------------------------------
def test_read_data_errors(tmp_path):
    empty = tmp_path / 'empty.csv'
    empty.write_text('', encoding='utf-8')
    cases = (
        ('first column not time', KeyError,
         _write_csv(tmp_path, 'k.csv', ['foo', 'A'], [(1.0, 2.0), (3.0, 4.0)])),
        ('unknown unit', ValueError,
         _write_csv(tmp_path, 'u.csv', ['time[bananas]', 'A'], [(1.0, 2.0)])),
        ('non-time unit', ValueError,
         _write_csv(tmp_path, 'n.csv', ['time[kg]', 'A'], [(1.0, 2.0)])),
        ('empty bracket', ValueError,
         _write_csv(tmp_path, 'b.csv', ['time[]', 'A'], [(1.0, 2.0)])),
        ('empty header', ValueError, str(empty)),
        ('header only, no rows', ValueError,
         _write_csv(tmp_path, 'h.csv', ['time', 'A'], [])),
        ('non-float value', TypeError,
         _write_csv(tmp_path, 't.csv', ['time', 'A'],
                    [(1.0, 'not_a_number'), (2.0, 3.0)])),
        ('missing file', FileNotFoundError, str(tmp_path / 'does_not_exist.csv')),
    )
    failures = []
    for label, exc_type, file in cases:
        _expect_raises(failures, label, exc_type, TimeProfile.read_data, file)
    assert not failures, '\n'.join(failures)


def test_parse_time_header_errors():
    failures = []
    for header in ('time[]', 'time[bananas]', 'time[kg]'):
        _expect_raises(failures, header, ValueError,
                       TimeProfile._parse_time_header, header)
    assert not failures, '\n'.join(failures)


# ---------------------------------------------------------------------------
# 3) exp.time property + time_unit attribute
# ---------------------------------------------------------------------------
def test_time_profile_time_row_and_unit_attribute():
    data = np.array([[0.0, 1.0, 2.0], [10.0, 20.0, 30.0]], dtype=float)
    exp = _make_time_profile(['A'], data, time_unit='ms')
    np.testing.assert_array_equal(exp.time, data[0])
    # property exposes row 0 of self.data (shares underlying memory)
    assert np.shares_memory(exp.time, exp.data)
    np.testing.assert_array_equal(exp.time, exp.data[0])
    assert exp.time_unit == 'ms'
    assert _make_time_profile(['A'], data).time_unit == 's'


# ---------------------------------------------------------------------------
# 4) validate_pair
# ---------------------------------------------------------------------------
def test_validate_pair(tmp_path):
    """Same unit and mixed-but-equivalent units match; a tiny difference is
    tolerated; mixed non-matching units, a header mismatch and a shape
    mismatch raise ValueError."""
    def _pair(name, d_header, d_rows, e_header, e_rows):
        d = _write_csv(tmp_path, f'{name}_d.csv', d_header, d_rows)
        e = _write_csv(tmp_path, f'{name}_e.csv', e_header, e_rows)
        dh, dm, _ = TimeProfile.read_data(d)
        eh, em, _ = TimeProfile.read_data(e)
        return dh, dm, eh, em, d, e

    rows = [(1.0, 5.0), (2.0, 6.0)]
    TimeProfile.validate_pair(*_pair('same', ['time[ms]', 'A'], rows,
                                     ['time[ms]', 'A'], rows))
    # 1 ms == 1000 us -> same seconds grid
    TimeProfile.validate_pair(*_pair('mixed', ['time[ms]', 'A'], rows,
                                     ['time[us]', 'A'],
                                     [(1000.0, 5.0), (2000.0, 6.0)]))
    headers = ['time', 'A']
    data = np.array([[0.0, 1.0, 2.0], [5.0, 6.0, 7.0]], dtype=float)
    error = data.copy()
    error[0] = error[0] + 1e-12
    TimeProfile.validate_pair(headers, data, headers, error, 'd.csv', 'e.csv')

    failures = []
    for label, args in (
            ('mixed non-matching units',
             _pair('nm', ['time[ms]', 'A'], rows, ['time[us]', 'A'], rows)),
            ('header mismatch',
             _pair('hm', ['time', 'A'], [(1.0, 5.0)], ['time', 'B'], [(1.0, 5.0)])),
            ('shape mismatch',
             _pair('sm', ['time', 'A'], rows, ['time', 'A'],
                   rows + [(3.0, 7.0)]))):
        _expect_raises(failures, label, ValueError, TimeProfile.validate_pair, *args)
    assert not failures, '\n'.join(failures)


# ---------------------------------------------------------------------------
# plot (matplotlib stubbed; x_unit validated like convert_time)
# ---------------------------------------------------------------------------
class _Ax:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return _rec

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def _stub_matplotlib(monkeypatch):
    import sys
    import types
    mpl = types.ModuleType('matplotlib')
    plt = types.ModuleType('matplotlib.pyplot')
    mpl.pyplot = plt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'matplotlib', mpl)
    monkeypatch.setitem(sys.modules, 'matplotlib.pyplot', plt)


_PLOT_DATA = [[0.0, 1e-3, 2e-3], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


def test_plot_draws_series_error_bars_and_accepts_time_units(monkeypatch):
    _stub_matplotlib(monkeypatch)
    time = np.array(_PLOT_DATA[0])

    # (a) density, ms, error bars, colors and legend
    tp = _make_time_profile(['A', 'B'], _PLOT_DATA)
    ax = _Ax()
    tp.plot(ax, y_unit='density', x_unit='ms', colors=['r', 'b'], legend=['a', 'b'])
    plots, bars = ax.named('plot'), ax.named('errorbar')
    assert len(plots) == 2 and len(bars) == 2
    assert np.allclose(plots[0][1][0], time * 1e3)
    assert np.allclose(plots[1][1][1], [4.0, 5.0, 6.0])
    assert [p[2]['label'] for p in plots] == ['a', 'b']
    assert [p[2]['color'] for p in plots] == ['r', 'b']
    assert len(ax.named('legend')) == 1
    assert ax.named('set_xlabel')[0][1] == ('Time (ms)',)
    title = ax.named('set_title')[0][1][0]
    assert 'A, B' in title and '500.0 K' in title and '101325.0 Pa' in title

    # (b) ratio, seconds, no error, no legend
    tp = _make_time_profile(['A', 'B'], _PLOT_DATA)
    tp.error = None
    ax = _Ax()
    tp.plot(ax, y_unit='ratio', x_unit='s', add_legend=False)
    plots = ax.named('plot')
    assert np.allclose(plots[0][1][0], time)
    assert [p[2]['label'] for p in plots] == [None, None]
    assert [p[2]['color'] for p in plots] == [None, None]
    assert ax.named('errorbar') == [] and ax.named('legend') == []
    assert ax.named('set_xlabel')[0][1] == ('Time (s)',)

    # (c) minutes, (d) microseconds
    for unit, expected in (('min', time / 60.0), ('us', time * 1e6)):
        ax = _Ax()
        _make_time_profile(['A', 'B'], _PLOT_DATA).plot(ax, x_unit=unit)
        assert np.allclose(ax.named('plot')[0][1][0], expected), unit


def test_plot_rejects_bad_arguments_and_missing_matplotlib(monkeypatch):
    import sys
    import pytest
    _stub_matplotlib(monkeypatch)
    tp = _make_time_profile(['A', 'B'], _PLOT_DATA)
    for kwargs, exc in (({'y_unit': 1}, TypeError),
                        ({'x_unit': 1}, TypeError),
                        ({'y_unit': 'furlong'}, ValueError),
                        ({'x_unit': 'kg'}, ValueError),
                        ({'x_unit': 'bananas'}, ValueError),
                        ({'colors': ['r']}, ValueError),
                        ({'legend': ['only one']}, ValueError)):
        with pytest.raises(exc):
            tp.plot(_Ax(), **kwargs)
    with pytest.raises(ValueError, match='x_unit must be a time unit'):
        tp.plot(_Ax(), x_unit='kg')

    monkeypatch.setitem(sys.modules, 'matplotlib.pyplot', None)
    with pytest.raises(ImportError, match='matplotlib is required'):
        tp.plot(_Ax())
