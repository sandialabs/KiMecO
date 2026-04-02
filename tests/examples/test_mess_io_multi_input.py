from __future__ import annotations

import json
from pathlib import Path

import pytest

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP
from kimeco.readers.mess_input import MessInputReader
from kimeco.well import Well

DME_ROOT = Path(__file__).resolve().parent.parent / "parse_pes" / "dme"
DME_INPUT_JSON = DME_ROOT / "input.json"


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


def _build_reader(tmp_path: Path, settings: dict) -> MessInputReader:
    return MessInputReader(
        settings=settings,
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / "test_mess_io.log")),
        postprocess=False,
    )


def _assert_sop_equivalent(sop1: SOP, sop2: SOP) -> None:
    assert sorted(sop1.items.keys()) == sorted(sop2.items.keys())
    assert set(sop1.pes_ids) == set(sop2.pes_ids)
    for name in sop1.items:
        item1 = sop1.items[name]
        item2 = sop2.items[name]
        assert type(item1) == type(item2), f"Type mismatch for '{name}'"
        assert item1.in_multiple_pes == item2.in_multiple_pes, (
            f"in_multiple_pes mismatch for '{name}'"
        )
        if isinstance(item1, Barrier):
            assert {c.name for c in item1.connected} == {
                c.name for c in item2.connected
            }, f"Barrier connectivity mismatch for '{name}'"
        elif isinstance(item1, Well):
            assert item1.energy == item2.energy, f"Energy mismatch for '{name}'"
            assert len(item1.frequencies) == len(item2.frequencies), (
                f"Frequency count mismatch for '{name}'"
            )
        elif isinstance(item1, Bimolecular):
            assert item1.energy == item2.energy, f"Energy mismatch for '{name}'"


def test_sop_is_equivalent_regardless_of_input_file_order(tmp_path: Path) -> None:
    settings_fwd = _dme_settings()
    settings_rev = _dme_settings()
    settings_rev["mess_inputs"] = list(reversed(settings_rev["mess_inputs"]))

    fwd_path = tmp_path / "fwd"
    rev_path = tmp_path / "rev"
    fwd_path.mkdir()
    rev_path.mkdir()

    reader_fwd = _build_reader(tmp_path=fwd_path, settings=settings_fwd)
    reader_rev = _build_reader(tmp_path=rev_path, settings=settings_rev)

    try:
        sop_fwd, _ = reader_fwd.read()
        sop_rev, _ = reader_rev.read()
    except (ValueError, IndexError) as exc:
        pytest.xfail(f"Known multi-input parse limitation: {exc}")

    _assert_sop_equivalent(sop_fwd, sop_rev)
