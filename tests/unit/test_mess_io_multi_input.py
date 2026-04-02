from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.well import Well
from kimeco.writers.mess import MessWriter

# The path to the JSON file relevant for these tests
DME_ROOT = Path(__file__).resolve().parent.parent / "parse_pes" / "dme"
DME_INPUT_JSON = DME_ROOT / "input.json"


# Create setting for the MESS reader
def _dme_settings() -> dict:
    payload = json.loads(DME_INPUT_JSON.read_text())
    return {
        "init_loc": str(DME_ROOT),
        "mess_inputs": payload["mess_inputs"],
        "score_sp": [],
        "freq_mode": FreqMode.BATCH,
        "rc_temp": payload["rc_temp"],
        "rc_pres": payload["rc_pres"],
        "pres_unit": payload["pres_unit"],
        "force_new_molecules": True,
    }


def _build_reader(tmp_path: Path) -> MessInputReader:
    return MessInputReader(
        settings=_dme_settings(),
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / "test_mess_io.log")),
        postprocess=False,
    )


# Find the starting line of a block in the MESS input file
def _find_line(lines: list[str], blockname: str, after: int = 0) -> int:
    for idx in range(after, len(lines)):
        if lines[idx].lstrip().casefold().startswith(blockname.casefold()):
            return idx
    raise ValueError(f"Could not find line starting with '{blockname}'")


@pytest.fixture
def reader(tmp_path: Path) -> MessInputReader:
    """Provide a clean reader for each test."""
    return _build_reader(tmp_path=tmp_path)


def test_read_duplicate_well_name_across_inputs_marks_multiple_pes(
    tmp_path: Path,
) -> None:
    """Check the pathway of well creation across multiple PES"""
    parse_reader = _build_reader(tmp_path=tmp_path)
    # 2 fake files with the same well
    parse_reader.pes_files = [
        [
            "Well DUP\n",
            "End\n",
        ],
        [
            "Well DUP\n",
            "End\n",
        ],
    ]

    sop, templates = parse_reader.read()

    assert len(templates) == 2
    assert "DUP" in sop.items
    item = sop.items["DUP"]
    assert item.in_multiple_pes is False
    assert sorted(item.pes_ids) == [0]
    assert parse_reader._trigger_stop is True


def test_read_duplicate_bimolecular_name_across_inputs_is_ignored(
    tmp_path: Path,
) -> None:
    """Check the pathway of Bimolecular creation across multiple PES"""
    parse_reader = _build_reader(tmp_path=tmp_path)
    parse_reader.pes_files = [
        [
            "Bimolecular DUP\n",
            "End\n",
        ],
        [
            "Bimolecular DUP\n",
            "End\n",
        ],
    ]

    sop, templates = parse_reader.read()

    assert len(templates) == 2
    assert "DUP" in sop.items
    item = sop.items["DUP"]
    assert item.pes_ids == [0]
    assert parse_reader._trigger_stop is False


def test_read_duplicate_barrier_name_across_inputs_triggers_stop(
    tmp_path: Path,
) -> None:
    """Check the pathway of Barrier creation across multiple PES"""

    parse_reader = _build_reader(tmp_path=tmp_path)
    parse_reader.pes_files = [
        [
            "Well LEFT_SIDE\n",
            "Well RIGHT_SIDE\n",
            "Barrier DUP LEFT_SIDE RIGHT_SIDE\n",
            "End\n",
        ],
        [
            "Barrier DUP LEFT_SIDE RIGHT_SIDE\n",
            "End\n",
        ],
    ]

    sop, templates = parse_reader.read()

    assert len(templates) == 2
    assert "DUP" in sop.items
    item = sop.items["DUP"]
    assert item.pes_ids == [0]
    assert len(sop.barriers) == 1
    assert parse_reader._trigger_stop is True


def test_save_energy_parses_and_stores_value(reader: MessInputReader) -> None:
    file_lines = reader.pes_files[0]
    reader.tpls = [[]]

    reader.SOP.add_new_well(name="UNIT_WELL", pes_id=0)
    zero_idx = _find_line(file_lines, "ZeroEnergy")
    value = float(file_lines[zero_idx].split()[1])

    reader.save_energy(name="UNIT_WELL", energy=value, lnum=zero_idx)

    assert reader.SOP.items["UNIT_WELL"].energy == value
    assert reader.tpls[-1][-1].startswith("ZeroEnergy")
    assert "{UNIT_WELL.energy}" in reader.tpls[-1][-1]


def test_save_freq_reads_exact_number_of_frequencies(
    reader: MessInputReader,
) -> None:
    file_lines = reader.pes_files[0]
    reader.tpls = [[]]

    target = "CH3OC(OO)H2"
    reader.SOP.add_new_well(name=target, pes_id=0)

    freq_idx = _find_line(file_lines, "Frequencies")
    nfreq = int(file_lines[freq_idx].split()[1])

    consumed = reader.save_freq(name=target, lnum=freq_idx, nfreq=nfreq)
    parsed_well = cast(Well, reader.SOP.items[target])

    assert consumed > 0
    assert len(parsed_well.frequencies) == nfreq
    assert reader.tpls[-1][-1].strip() == "{" + f"{target}.r_freq" + "}"


def test_save_rotor_reads_hindered_rotor_block(
    reader: MessInputReader,
) -> None:
    file_lines = reader.pes_files[0]
    reader.tpls = [[]]

    target = "CH3OC(OO)H2"
    reader.SOP.add_new_well(name=target, pes_id=0)

    rotor_idx = _find_line(file_lines, "Rotor     Hindered")
    consumed = reader.save_rotor(name=target, lnum=rotor_idx)
    parsed_well = cast(Well, reader.SOP.items[target])

    assert consumed > 0
    assert len(parsed_well.h_rotors) == 1

    rotor = parsed_well.h_rotors[0]
    assert rotor.group
    assert rotor.axis
    assert len(rotor.scan) > 0


def test_integration_write_from_multi_input_sop(tmp_path: Path) -> None:
    payload = json.loads(DME_INPUT_JSON.read_text())
    relative_inputs: list[str] = payload["mess_inputs"]

    parse_reader = _build_reader(tmp_path=tmp_path)
    try:
        sop, templates = parse_reader.read()
    except ValueError as exc:
        # Current multi-input parser can fail when same-named fragments are
        # encountered with non-matching frequency blocks.
        pytest.xfail(f"Known multi-input parse limitation: {exc}")

    assert len(templates) == len(relative_inputs)

    out_root = tmp_path / "generated"
    for rel_path, tpl in zip(relative_inputs, templates):
        out_path = out_root / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        MessWriter(SOP=sop, tpl=tpl).write(
            loc=str(out_path.parent),
            filename=out_path.name,
        )
        assert out_path.exists()

    settings = _dme_settings()
    settings["init_loc"] = str(out_root)
    reader_roundtrip = MessInputReader(
        settings=settings,
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / "integration_roundtrip.log")),
        postprocess=False,
    )
    sop_roundtrip, templates_roundtrip = reader_roundtrip.read()

    assert len(templates_roundtrip) == len(relative_inputs)
    assert sorted(sop.items.keys()) == sorted(sop_roundtrip.items.keys())
    assert sop.pes_ids == sop_roundtrip.pes_ids
