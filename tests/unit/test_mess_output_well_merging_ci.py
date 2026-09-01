"""CI-safe tests for ``MessOutputReader.well_merging``.

``well_merging`` is the merged-well detector that gates the second MESS pass in
the emitted automech driver: it returns ``True`` as soon as any *T/P-dependent*
rate-coefficient cell is missing (rendered by MESS as ``***``).

The contract exercised here:

* only the ``Species-Species Rate Tables`` section is scanned;
* only tables introduced by a ``Temperature = ... Pressure = ...`` header count
  - the ``High Pressure Rate Coefficients`` blocks legitimately contain ``***``
  and must be ignored;
* the ``_______________`` rule terminates the scan;
* only the value cells (``split()[1:]``) are inspected, never the row label;
* the file is read, never written.

Everything runs on plain text fixtures - no MESS binary, no SOP, no settings.
"""
from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

import pytest

from kimeco.readers.mess_output import MessOutputReader


# Repository-shipped MESS output used as the "healthy" real-world fixture.
_REAL_OUT = (Path(__file__).resolve().parents[2]
             / 'example' / 'mess_input_ethyl_oxidation.out')


def _write(tmp_path: Path, body: str, name: str = 'mess.out') -> str:
    """Write a dedented fixture and return its path."""
    target = tmp_path / name
    target.write_text(textwrap.dedent(body))
    return str(target)


# A minimal, complete, healthy section: one HP block (with legitimate ``***``)
# followed by one T/P table whose cells are all present.
_HEALTHY = """\
Species-Species Rate Tables:

Temperature = 550 K

High Pressure Rate Coefficients:

From\\To            W1        W2
W1                ***      0.027
W2            2.4e+04        ***

Temperature = 550 K    Pressure = 1 bar

From\\To            W1        W2
W1                5.42    0.00363
W2            3.34e+03   2.01e+05

______________________________________________________________________
"""


# ---------------------------------------------------------------------------
# Standard contract
# ---------------------------------------------------------------------------
def test_real_mess_output_without_missing_tp_rates_is_not_merging() -> None:
    """The shipped, fully converged MESS output must report no merging.

    It contains ``***`` cells, but only inside High Pressure blocks.
    """
    assert _REAL_OUT.is_file(), f'missing fixture: {_REAL_OUT}'
    assert MessOutputReader.well_merging(str(_REAL_OUT)) is False


def test_synthetic_healthy_section_is_not_merging(tmp_path: Path) -> None:
    assert MessOutputReader.well_merging(_write(tmp_path, _HEALTHY)) is False


def test_starred_tp_cell_reports_merging(tmp_path: Path) -> None:
    """A single missing coefficient in a T/P table flips the gate to True."""
    path = _write(tmp_path, """\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                5.42        ***
        W2            3.34e+03   2.01e+05

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is True


def test_high_pressure_block_stars_are_ignored(tmp_path: Path) -> None:
    """``***`` in a High Pressure table is legitimate, not a merged well."""
    path = _write(tmp_path, """\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                5.42    0.00363
        W2            3.34e+03   2.01e+05

        Temperature = 550 K

        High Pressure Rate Coefficients:

        From\\To            W1        W2
        W1                 ***        ***
        W2                 ***        ***

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is False


def test_terminator_stops_scan_before_trailing_starred_section(
        tmp_path: Path) -> None:
    """Everything after the ``____`` rule is out of scope for the gate.

    Without the ``break`` the trailing (starred) T/P-looking table below would
    wrongly report merging.
    """
    path = _write(tmp_path, """\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                5.42    0.00363
        W2            3.34e+03   2.01e+05

        ______________________________________________________________________

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                 ***        ***
        W2                 ***        ***

        """)
    assert MessOutputReader.well_merging(path) is False


def test_well_merging_is_a_staticmethod_callable_without_an_instance(
        tmp_path: Path) -> None:
    """The gate runs on the compute node with no SOP/settings/logger."""
    raw = inspect.getattr_static(MessOutputReader, 'well_merging')
    assert isinstance(raw, staticmethod)
    params = list(inspect.signature(MessOutputReader.well_merging).parameters)
    assert params == ['filename']
    # No instantiation, no settings dict, no SOP, no KMOLogger.
    assert MessOutputReader.well_merging(_write(tmp_path, _HEALTHY)) is False


def test_well_merging_does_not_mutate_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEALTHY)
    before = Path(path).read_bytes()
    MessOutputReader.well_merging(path)
    assert Path(path).read_bytes() == before


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('column', [0, 1, 2])
def test_star_detected_in_any_value_column(tmp_path: Path,
                                           column: int) -> None:
    """The scan covers every value cell, not just the first or last."""
    cells = ['5.42', '0.00363', '7.7e+02']
    cells[column] = '***'
    path = _write(tmp_path, f"""\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2        W3
        W1        {cells[0]:>10} {cells[1]:>10} {cells[2]:>10}
        W2            3.34e+03   2.01e+05   1.00e+02

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is True


@pytest.mark.parametrize('token', ['***', '*', '*****', '-***'])
def test_all_star_token_variants_report_merging(tmp_path: Path,
                                                token: str) -> None:
    """MESS renders overflow/missing cells with variable star widths."""
    path = _write(tmp_path, f"""\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                5.42 {token:>10}
        W2            3.34e+03   2.01e+05

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is True


def test_star_in_row_label_is_ignored(tmp_path: Path) -> None:
    """Only ``split()[1:]`` is scanned, so a starred species name is safe."""
    path = _write(tmp_path, """\
        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To          W*1        W2
        W*1               5.42    0.00363
        W2            3.34e+03   2.01e+05

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is False


def test_empty_file_is_not_merging(tmp_path: Path) -> None:
    path = tmp_path / 'empty.out'
    path.write_text('')
    assert MessOutputReader.well_merging(str(path)) is False


def test_truncated_table_without_trailing_blank_line_still_detects_star(
        tmp_path: Path) -> None:
    """A MESS run killed mid-table must not hide a missing coefficient."""
    path = tmp_path / 'truncated.out'
    path.write_text(
        'Species-Species Rate Tables:\n'
        '\n'
        'Temperature = 550 K    Pressure = 1 bar\n'
        '\n'
        'From\\To            W1        W2\n'
        'W1                5.42        ***\n'
        'W2            3.34e+03')
    assert MessOutputReader.well_merging(str(path)) is True


def test_truncated_healthy_table_is_not_merging(tmp_path: Path) -> None:
    """Truncation alone is not merging - only missing star cells are."""
    path = tmp_path / 'truncated_ok.out'
    path.write_text(
        'Species-Species Rate Tables:\n'
        '\n'
        'Temperature = 550 K    Pressure = 1 bar\n'
        '\n'
        'From\\To            W1        W2\n'
        'W1                5.42    0.00363\n'
        'W2            3.34e+03')
    assert MessOutputReader.well_merging(str(path)) is False


def test_headers_are_case_and_whitespace_insensitive(tmp_path: Path) -> None:
    """Section/table detection uses lstrip + casefold on the headers."""
    path = _write(tmp_path, """\
           SPECIES-SPECIES RATE TABLES:

           TEMPERATURE = 550 K    PRESSURE = 1 bar

           From\\To            W1        W2
           W1                5.42        ***

           ____________________________________________________________
           """)
    assert MessOutputReader.well_merging(path) is True


def test_terminator_immediately_after_section_header(tmp_path: Path) -> None:
    """An empty rate-table section is not merging."""
    path = _write(tmp_path, """\
        Species-Species Rate Tables:
        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is False


def test_lines_before_the_section_header_are_ignored(tmp_path: Path) -> None:
    """Starred preamble tables must not trip the gate."""
    path = _write(tmp_path, """\
        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                 ***        ***

        Species-Species Rate Tables:

        Temperature = 550 K    Pressure = 1 bar

        From\\To            W1        W2
        W1                5.42    0.00363

        ______________________________________________________________________
        """)
    assert MessOutputReader.well_merging(path) is False


def test_missing_file_propagates_filenotfounderror(tmp_path: Path) -> None:
    """``well_merging`` itself does not guard existence.

    The emitted driver checks ``os.path.isfile`` before calling it (see
    ``test_automech_driver_merging_ci.py``), so the raw helper is only ever
    invoked on a path known to exist.
    """
    with pytest.raises(FileNotFoundError):
        MessOutputReader.well_merging(str(tmp_path / 'does_not_exist.out'))
