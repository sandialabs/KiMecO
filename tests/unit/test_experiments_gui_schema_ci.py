import pytest

from kimeco.default_settings import default_settings
from kimeco.gui.input_sections.experiments_section import (
    _make_empty_experiment,
)
from kimeco.gui.input_sections.save_load_write_section import (
    _build_experiments_user_settings,
)
from kimeco.gui.parameters_metadata import (
    get_all_parameters_by_category,
    get_parameter_metadata,
)


def test_empty_experiment_store_has_no_per_experiment_scoring_func() -> None:
    exp = _make_empty_experiment(1)

    assert "scoring_func" not in exp


def test_written_experiment_payload_drops_legacy_scoring_func() -> None:
    experiments_store = [
        {
            "id": 1,
            "temp": 1000.0,
            "pres": 760.0,
            "weight": 1.0,
            "pres_unit": "torr",
            "cantera_tpl": "template.cti",
            "scoring_func": "weighteddif",
            "data_file": "exp.csv",
            "error_file": "err.csv",
            "init_mode": "ratio",
            "init_value": "H2:0.5, O2:0.5",
            "w_species": {"OH": 2.0},
        }
    ]

    payload = _build_experiments_user_settings(experiments_store)

    assert len(payload) == 1
    assert "scoring_func" not in payload[0]


def test_use_automech_is_bool_in_defaults_and_gui_metadata() -> None:
    """use_automech defaults to the bool False and surfaces as a bool in the GUI
    metadata."""
    # -- test_use_automech_default_is_bool_false
    assert "use_automech" in default_settings
    value = default_settings["use_automech"]
    assert isinstance(value, bool)
    assert value is False

    # -- test_use_automech_surfaces_as_bool_in_gui_metadata
    meta = get_parameter_metadata("use_automech")

    assert meta.default is False
    assert meta.param_type == "bool"
    assert meta.category == "Rate Coefficients"

    by_category = get_all_parameters_by_category()
    names = {m.name for m in by_category["Rate Coefficients"]}
    assert "use_automech" in names


@pytest.mark.parametrize("key, default, param_type", [
    ("prompt_reactions", False, "bool"),
    ("prompt_ped_model", "rovib_dos", "str"),
    ("prompt_bf_threshold", 0.01, "float"),
])
def test_prompt_keys_in_defaults_and_gui_metadata(key, default,
                                                  param_type) -> None:
    """The three prompt keys: default value and type, GUI type inferred
    from it, category "Rate Coefficients" with a description, listed under
    that category."""
    assert key in default_settings
    value = default_settings[key]
    assert value == default and type(value) is type(default)

    meta = get_parameter_metadata(key)
    assert meta.default == default
    assert meta.param_type == param_type
    assert meta.category == "Rate Coefficients"
    assert meta.description.strip()

    names = {m.name for m in get_all_parameters_by_category()[
        "Rate Coefficients"]}
    assert key in names




# ===========================================================================
# Experiment and SOP GUI callbacks (callback_context patched per call)
# ===========================================================================
import os  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from dash import no_update  # noqa: E402

import kimeco.gui.input_sections.experiments_section as exp_sec  # noqa: E402
import kimeco.gui.input_sections.sop_section as sop_sec  # noqa: E402
from kimeco.experiments.t_profile import TimeProfile  # noqa: E402
from kimeco.gui.input_sections.file_browser import FileBrowserDropdown  # noqa: E402


def _trigger(monkeypatch, module, triggered_id) -> None:
    monkeypatch.setattr(module, 'callback_context',
                        SimpleNamespace(triggered_id=triggered_id))


def _full_tpl() -> str:
    return ' '.join('{' + k + '}' for k in sorted(TimeProfile.REQUIRED_TPL_KEYS))


def test_validate_cantera_template_path_branches(tmp_path, monkeypatch) -> None:
    check = exp_sec._validate_cantera_template_path
    files = {'empty.tpl': '  \n', 'brace.tpl': '{', 'one.tpl': '{' + sorted(
        TimeProfile.REQUIRED_TPL_KEYS)[0] + '}', 'extra.tpl': _full_tpl() + ' {bogus}',
        'ok.tpl': _full_tpl(), 'unreadable.tpl': 'x'}
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    path = {name: str(tmp_path / name) for name in files}

    assert check('') == (False, 'Select a Cantera template file.')
    assert check(str(tmp_path / 'nope.tpl')) == (False, 'Cantera template file not found.')
    assert check(path['empty.tpl']) == (False, 'Cantera template file is empty.')
    ok, msg = check(path['brace.tpl'])
    assert not ok and msg.startswith('Invalid template format')
    ok, msg = check(path['one.tpl'])
    assert not ok and msg.startswith('Missing template keywords: ')
    ok, msg = check(path['extra.tpl'])
    assert (ok, msg) == (False, 'Unsupported template keywords: bogus')
    assert check('  ' + path['ok.tpl'] + ' ') == (True, 'Cantera template keywords are valid.')

    def _boom(*a, **k):
        raise OSError('denied')

    monkeypatch.setattr(exp_sec, 'open', _boom, raising=False)
    assert check(path['unreadable.tpl']) == (False, 'Cannot read template: denied')


def test_validate_cantera_templates_button(tmp_path, monkeypatch) -> None:
    (tmp_path / 'ok.tpl').write_text(_full_tpl())
    (tmp_path / 'bad.tpl').write_text('{only}')
    hidden = {'display': 'none'}
    paths = ['', str(tmp_path / 'ok.tpl'), str(tmp_path / 'bad.tpl')]

    _trigger(monkeypatch, exp_sec, None)
    assert exp_sec.validate_cantera_templates([0, 0, 0], paths, None, None) == (
        [''] * 3, [hidden] * 3)
    for trig in ({'index': None}, {'index': 3}):
        _trigger(monkeypatch, exp_sec, trig)
        assert exp_sec.validate_cantera_templates([0] * 3, paths, ['m'], [hidden]) == (
            ['m', '', ''], [hidden] * 3)

    _trigger(monkeypatch, exp_sec, {'index': 0})
    msgs, styles = exp_sec.validate_cantera_templates([1, 0, 0], paths, None, None)
    assert msgs[0] == 'Select a reactor template file first.'
    assert styles[0] == {'display': 'block', 'color': 'red'}

    _trigger(monkeypatch, exp_sec, {'index': 1})
    msgs, styles = exp_sec.validate_cantera_templates([0, 1, 0], paths, None, None)
    assert msgs[1] == 'Cantera template keywords are valid.'
    assert styles[1] == {'display': 'block', 'color': 'green', 'fontWeight': 'bold'}

    _trigger(monkeypatch, exp_sec, {'index': 2})
    msgs, styles = exp_sec.validate_cantera_templates([0, 0, 1], paths, None, None)
    assert msgs[2].startswith('Missing template keywords')
    assert styles[2] == {'display': 'block', 'color': 'red', 'fontWeight': 'normal'}


def test_update_experiment_file_browser_states(tmp_path, monkeypatch) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'a.csv').write_text('x')
    browser = FileBrowserDropdown(root_dir=str(tmp_path))
    monkeypatch.setattr(exp_sec, '_EXP_BROWSER', browser)
    root, sub = str(tmp_path), str(tmp_path / 'sub')
    ids = [{'index': 0, 'field': 'cantera_tpl'}, {'index': 1, 'field': 'data_file'}]
    update = exp_sec.update_experiment_file_browser_states

    def _call(selected, **state):
        return update(selected, None, state.get('cwd'), state.get('sel'),
                      state.get('opts'), state.get('paths'), state.get('vals'), ids)

    # (a) non-dict trigger, (b) dict trigger matching no browser: padded only
    for trig in (None, {'index': 7, 'field': 'data_file'}):
        _trigger(monkeypatch, exp_sec, trig)
        cwd, sel, opts, paths, vals = _call([None, None])
        assert cwd == [root, root] and sel == [None, None] and vals == [None, None]
        assert opts == [browser.build_options(root)] * 2
        assert [p.children for p in paths] == [browser.path_label(root).children] * 2

    # (c) directory selected in browser 1
    _trigger(monkeypatch, exp_sec, {'index': 1, 'field': 'data_file'})
    cwd, sel, opts, paths, vals = _call([None, sub], vals=['x', 'y'])
    assert cwd == [root, sub] and sel == [None, None]
    assert opts[1] == browser.build_options(sub) and opts[0] == browser.build_options(root)
    assert paths[1].children == browser.path_label(sub).children
    assert vals == ['x', None]

    # (d) file selected in browser 0
    _trigger(monkeypatch, exp_sec, {'index': 0, 'field': 'cantera_tpl'})
    cwd, sel, _, _, _ = _call([str(tmp_path / 'a.csv'), None], cwd=[root, sub])
    assert cwd == [root, sub]
    assert sel == [str(tmp_path / 'a.csv'), None]


def test_apply_selected_file_to_experiment_field(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ('tpl.tpl', 'd.csv', 'e.csv', 'other.csv'):
        (tmp_path / name).write_text('x')
    f = {name: str(tmp_path / name) for name in ('tpl.tpl', 'd.csv', 'e.csv', 'other.csv')}
    pairs = [
        ({'index': 0, 'field': 'cantera_tpl'}, f['tpl.tpl']),
        ({'index': 0, 'field': 'data_file'}, f['d.csv']),
        ({'index': 0, 'field': 'error_file'}, f['e.csv']),
        ({'index': 0, 'field': 'data_file'}, str(tmp_path / 'missing.csv')),
        ({'index': 0, 'field': 'error_file'}, None),
        ('not-a-dict', f['other.csv']),
        ({'field': 'data_file'}, f['other.csv']),
        ({'index': 5, 'field': 'cantera_tpl'}, f['other.csv']),
        ({'index': 3, 'field': 'data_file'}, f['other.csv']),
        ({'index': 3, 'field': 'error_file'}, f['other.csv']),
    ]
    out = exp_sec.apply_selected_file_to_experiment_field(
        [p[1] for p in pairs], [p[0] for p in pairs], ['old'], ['old'], ['old'])
    assert out == (['tpl.tpl'], ['d.csv'], ['e.csv'])
    assert exp_sec.apply_selected_file_to_experiment_field(None, None, None, None, None) == (
        [], [], [])


def _add(experiments, **fields):
    keys = ('temps', 'press', 'weights', 'units', 'modes', 'tpls', 'data', 'errors',
            'inits', 'names', 'values')
    args = [fields.get(k, []) for k in keys]
    return exp_sec.add_experiment(fields.get('n_clicks', 1), fields.get('clicks', []),
                                  experiments, *args)


def test_add_experiment_saves_forms_and_appends(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _trigger(monkeypatch, exp_sec, 'add-experiment-button')

    saved, table = _add(None)
    assert saved == [exp_sec._make_empty_experiment(1)] and len(table) == 1

    stored = [{'id': 1, 'weight': 2.0, 'w_species': {'H': 1.0}}, {'id': 2, 'weight': 3.0}]
    saved, table = _add(stored, temps=[500.0], press=[1.0], weights=[None], units=['atm'],
                        modes=[None], tpls=[str(tmp_path / 't.tpl')], data=['  '],
                        errors=['e.csv'], inits=[None])
    assert len(saved) == 3 and len(table) == 3
    first, second, new = saved
    assert first == {'id': 1, 'weight': 1.0, 'w_species': {'H': 1.0}, 'temp': 500.0,
                     'pres': 1.0, 'pres_unit': 'atm', 'init_mode': 'ratio',
                     'cantera_tpl': 't.tpl', 'data_file': '', 'error_file': 'e.csv',
                     'init_value': ''}
    assert (second['temp'], second['pres'], second['weight']) == (None, None, 3.0)
    assert second['pres_unit'] == exp_sec.DEFAULT_PRESSURE_UNIT
    assert (second['cantera_tpl'], second['init_value']) == ('', '')
    assert new == exp_sec._make_empty_experiment(3)


def test_add_experiment_adds_species_weight_on_species_trigger(monkeypatch) -> None:
    stored = [{'id': 1, 'weight': 1.0}]
    species = {'type': 'exp-w-species-add', 'index': 0}
    cases = (
        ('parsed', species, [1], [' OH '], ['2.5'], {'OH': 2.5}),
        ('not numeric', species, [1], ['OH'], ['abc'], {'OH': 1.0}),
        ('negative', species, [1], ['OH'], [-1], None),
        ('empty name', species, [1], ['  '], [2.0], None),
        ('index out of range', {'type': 'exp-w-species-add', 'index': 5}, [1], ['OH'], [2.0], None),
        ('no click', species, [0], ['OH'], [2.0], None),
    )
    for label, trig, clicks, names, values, expected in cases:
        _trigger(monkeypatch, exp_sec, trig)
        saved, table = _add([dict(stored[0])], clicks=clicks, names=names, values=values)
        assert len(saved) == 1 and len(table) == 1, label
        assert saved[0].get('w_species') == expected, label


def test_update_mess_files_list(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'a.inp').write_text('x')
    a_inp = str(tmp_path / 'a.inp')
    update = sop_sec.update_mess_files_list

    _trigger(monkeypatch, sop_sec, 'sop-browser-selected-file')
    files = update(a_inp, [], None)
    assert files == ['a.inp']
    assert update(a_inp, [], files) == ['a.inp']
    assert update(str(tmp_path / 'missing.inp'), [], ['b.inp']) == ['b.inp']
    assert update(None, [], ['b.inp']) == ['b.inp']

    _trigger(monkeypatch, sop_sec, {'type': 'sop-remove-file', 'index': 'a.inp'})
    assert update(None, [None], ['a.inp', 'b.inp']) is no_update
    assert update(None, [1], ['a.inp', 'b.inp']) == ['b.inp']
    _trigger(monkeypatch, sop_sec, {'type': 'sop-remove-file', 'index': ''})
    assert update(None, [1], ['a.inp']) is no_update
    _trigger(monkeypatch, sop_sec, 'something-else')
    assert update(a_inp, [1], ['a.inp']) is no_update
    assert os.getcwd() == str(tmp_path)
