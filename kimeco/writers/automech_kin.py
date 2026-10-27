"""Emitter for the automech-driven two-pass MESS path.

``AutomechKinWriter`` mirrors :class:`kimeco.writers.mess.MessWriter`'s public
shape (``write(loc, filename)``) but, instead of substituting placeholders into
a MESS template, it serializes the read-only fields of a PES (wells,
bimoleculars, barriers) into a plain-Python ``PES_PAYLOAD`` literal and embeds
it - following ``simulation.py::q_up``'s inline-embedding precedent - into a
self-contained python driver script.

When executed on the compute node the emitted script:

1. rebuilds every species' MESS data string from the embedded payload using the
   public ``mess_io.writer`` API (``molecule``/``atom`` + the appropriate
   ``core_*``/``rotor_*`` calls);
2. assembles the reaction-channel section from ``well``/``bimolecular``/
   ``ts_sadpt`` calls;
3. builds the global energy-transfer section from ``energy_down`` +
   ``collision_frequency`` -> ``global_energy_transfer_input``;
4. builds the global keyword section via ``global_rates_input_v1`` on the
   embedded (possibly sub-grid) temperature/pressure grid, forwarding the
   header keys read from the parsed MESS input (CalculationMethod,
   ModelEnergyLimit, ExcessEnergyOverTemperature, ChemicalEigenvalueMax,
   EnergyStepOverTemperature, WellReductionThreshold, WellExtension,
   PEDSpecies, MicroEnerMin/Max/Step) when they are present in the payload,
   with side-output names of its own (``<name>P<slot>_ped.out``,
   ``<name>P<slot>_ke.out``);
5. writes the base input, runs MESS (pass 1), moves the pass-1 output to a
   leading-underscore intermediate, and only if rate coefficients are missing
   (merged wells) derives WellExtension caps via
   ``mess_io.well_lumped_input_file`` (at the lump pressure converted to atm,
   the unit mess_io parses the output in), overwrites the input and runs MESS
   (pass 2); otherwise the pass-1 output is moved back to
   ``<name>P<slot>.out`` and pass 2 is skipped.

External files referenced by bare relative filename (multirotor PES files,
barrierless rotd flux files) are read from the run cwd at execution time - they
are copied there through ``SOP.files2copy`` and are never inlined. The emitted
script reads no database; it imports only ``MessOutputReader`` from kimeco to
detect merged wells.

Each PES is written with its own input-file data (``SOP.pes_file_data``):
energies in the energy zero of its input file, its own Lennard-Jones pair
(collider + its second value) and masses, and its own per-file keys.
"""

import logging
from typing import Any

from kimeco.parameters import SOP, PesFileData
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from kimeco.barrier import Barrier


#: Keys of the warnings already emitted in this process by
#: ``AutomechKinWriter._hardcode_warnings`` (each is logged once only).
_warn_once: set[str] = set()

#: ``AtomDistanceMin`` hard-coded by mess_io's global_rates template.
_MESS_IO_ATOM_DISTANCE_MIN = 0.68793  # angstrom
#: Bohr radius in angstrom (AtomDistanceMin given in bohr).
_BOHR2ANG = 0.52917721092


def _log_once(key: str, msg: str) -> None:
    """Log ``msg`` as a warning the first time ``key`` is seen.

    Args:
        key (str): identity of the warning in ``_warn_once``.
        msg (str): warning text.
    """
    if key in _warn_once:
        return
    _warn_once.add(key)
    logging.getLogger(__name__).warning(msg)


# The runtime driver body. Only the top-level placeholders
# ({payload}/{name}/{slot}/{pres_unit}/{lump_pressure}/{lump_temp}) are
# substituted via str.format; the body is intentionally free of literal
# ``{``/``}`` (no f-strings, no dict/set literals other than dict()) so
# formatting is safe.
automech_kin_tpl = '''"""Auto-generated automech MESS driver. Do not edit."""
import os
import subprocess

from phydat import phycon
from mess_io.writer import molecule, atom
from mess_io.writer import core_rigidrotor, core_multirotor
from mess_io.writer import core_phasespace, core_rotd
from mess_io.writer import rotor_hindered, rotor_internal
from mess_io.writer import well, bimolecular, ts_sadpt, ts_variational
from mess_io.writer import global_energy_transfer_input, global_rates_input_v1
from mess_io.writer import messrates_inp_str
from mess_io.writer import energy_down, collision_frequency
from mess_io import well_lumped_input_file
from kimeco.readers.mess_output import MessOutputReader


PES_PAYLOAD = {payload}
NAME = "{name}"
SLOT = {slot}
PRES_UNIT = "{pres_unit}"
LUMP_PRESSURE = {lump_pressure}
LUMP_TEMP = {lump_temp}


def _geo_bohr(geo_ang):
    out = []
    for row in geo_ang:
        sym = row[0]
        xb = float(row[1]) / phycon.BOHR2ANG
        yb = float(row[2]) / phycon.BOHR2ANG
        zb = float(row[3]) / phycon.BOHR2ANG
        out.append((sym, (xb, yb, zb)))
    return out


def _hind_rot_str(rotors):
    out = ""
    for hr in rotors:
        pot = dict()
        for pair in hr["potential"]:
            pot[(float(pair[0]),)] = float(pair[1])
        kwargs = dict(
            group=hr["group"],
            axis=hr["axis"],
            symmetry=hr["symmetry"],
            potential=pot,
            therm_pow_max=hr["therm_pow_max"],
            potential_form="fourier")
        # Rotors read from a spline block keep their angles and are written
        # back as a spline.
        if hr.get("potential_form") == "spline":
            kwargs["potential_form"] = "spline"
        if hr.get("geo"):
            kwargs["geo"] = _geo_bohr(hr["geo"])
        out += rotor_hindered(**kwargs)
    return out


def _int_rot_str(int_rots):
    out = ""
    for ir in int_rots:
        out += rotor_internal(
            group=ir["group"],
            axis=ir["axis"],
            symmetry=ir["symmetry"],
            grid_size=ir["grid_size"],
            mass_exp_size=ir["mass_exp_size"],
            pot_exp_size=ir["pot_exp_size"],
            hmin=ir["hmin"],
            hmax=ir["hmax"])
    return out


def _species_data(spc):
    geo = _geo_bohr(spc["geo"])
    elec = spc["elec_levels"]
    if len(geo) == 1:
        return atom(mass=spc["mass"], elec_levels=elec)
    if spc["multi_rotors"]:
        mr = spc["multi_rotors"][0]
        core = core_multirotor(
            geo=geo,
            sym_factor=mr["sym_factor"],
            pot_surf_file=mr["pot_surf_file"],
            int_rot_str=_int_rot_str(mr["int_rots"]),
            interp_emax=mr["interp_emax"],
            quant_lvl_emax=mr["quant_lvl_emax"])
        return molecule(core=core, elec_levels=elec, freqs=spc["freqs"])
    core = core_rigidrotor(geo=geo, sym_factor=spc["sym_factor"])
    return molecule(
        core=core,
        elec_levels=elec,
        freqs=spc["freqs"],
        hind_rot=_hind_rot_str(spc["hind_rotors"]))


def _barrier_str(bar):
    kind = bar["kind"]
    elec = bar["elec_levels"]
    if kind == "saddle":
        core = core_rigidrotor(
            geo=_geo_bohr(bar["geo"]), sym_factor=bar["sym_factor"])
        data = molecule(
            core=core,
            elec_levels=elec,
            freqs=bar["freqs"],
            hind_rot=_hind_rot_str(bar["hind_rotors"]))
        tunnel = tunnel_eckart_wrap(
            bar["ifreq"], bar["well_depth1"], bar["well_depth2"])
        return ts_sadpt(
            ts_label=bar["label"],
            reac_label=bar["reac"],
            prod_label=bar["prod"],
            ts_data=data,
            zero_ene=bar["zero_ene"],
            tunnel=tunnel)
    if kind == "phasespace":
        core_kwargs = dict(
            geo1=_geo_bohr(bar["geo1"]),
            geo2=_geo_bohr(bar["geo2"]),
            sym_factor=bar["sym_factor"],
            stoich=bar["stoich"],
            pot_prefactor=bar["pot_prefactor"],
            pot_exp=bar["pot_exp"])
        if bar.get("tst_level"):
            core_kwargs["tstlvl"] = bar["tst_level"]
        core = core_phasespace(**core_kwargs)
        data = molecule(
            core=core,
            elec_levels=elec,
            freqs=bar["freqs"],
            hind_rot=_hind_rot_str(bar.get("hind_rotors", [])))
        return ts_sadpt(
            ts_label=bar["label"],
            reac_label=bar["reac"],
            prod_label=bar["prod"],
            ts_data=data,
            zero_ene=bar["zero_ene"])
    core = core_rotd(
        sym_factor=bar["sym_factor"],
        flux_file_name=bar["flux_file"],
        stoich=bar["stoich"])
    data = molecule(
        core=core,
        elec_levels=elec,
        freqs=bar["freqs"],
        hind_rot=_hind_rot_str(bar.get("hind_rotors", [])))
    return ts_sadpt(
        ts_label=bar["label"],
        reac_label=bar["reac"],
        prod_label=bar["prod"],
        ts_data=data,
        zero_ene=bar["zero_ene"])


def tunnel_eckart_wrap(ifreq, wd1, wd2):
    from mess_io.writer import tunnel_eckart
    return tunnel_eckart(imag_freq=ifreq, well_depth1=wd1, well_depth2=wd2)


def _energy_transfer_str():
    eps = PES_PAYLOAD["epsilons"]
    sig = PES_PAYLOAD["sigmas"]
    masses = PES_PAYLOAD["lj_masses"]
    if len(eps) < 2 or len(sig) < 2 or len(masses) < 2:
        return None
    edown = energy_down(
        exp_factor=PES_PAYLOAD["factor"],
        exp_power=PES_PAYLOAD["power"],
        exp_cutoff=PES_PAYLOAD["edown_cutoff"])
    collid = collision_frequency(
        eps1=eps[0] / phycon.EH2WAVEN,
        eps2=eps[1] / phycon.EH2WAVEN,
        sig1=sig[0] / phycon.BOHR2ANG,
        sig2=sig[1] / phycon.BOHR2ANG,
        mass1=masses[0],
        mass2=masses[1])
    return global_energy_transfer_input(edown, collid)


def _rxn_chan_str():
    # mess_io block writers (well/bimolecular/ts_sadpt) return strings
    # without a trailing newline (their Mako templates end with a backslash
    # line continuation), so blocks must be joined explicitly. Plain string
    # concatenation glues the next header onto the previous "End  ! ..."
    # comment (e.g. "End  ! WellWell CH2CH2OOH"), which makes MESS abort
    # with "Model::init: unknown keyword Species".
    blocks = []
    for w in PES_PAYLOAD["wells"]:
        blocks.append(well(
            well_label=w["label"],
            well_data=_species_data(w),
            zero_ene=w["zero_ene"]))
    for b in PES_PAYLOAD["bimols"]:
        f1 = b["frag1"]
        f2 = b["frag2"]
        bimol_kwargs = dict(
            bimol_label=b["label"],
            spc1_label=f1["label"],
            spc1_data=_species_data(f1),
            spc2_label=f2["label"],
            spc2_data=_species_data(f2),
            ground_ene=b["ground_ene"])
        # Fragment lines carrying the MESS density keyword in the input.
        if b.get("frag1_density"):
            bimol_kwargs["calc_spc1_density"] = True
        if b.get("frag2_density"):
            bimol_kwargs["calc_spc2_density"] = True
        blocks.append(bimolecular(**bimol_kwargs))
    for bar in PES_PAYLOAD["barriers"]:
        blocks.append(_barrier_str(bar))
    return "\\n".join(blocks)


def _globkey_str(out_name, well_extension):
    kwargs = dict(
        temperatures=PES_PAYLOAD["grid_temp"],
        pressures=PES_PAYLOAD["grid_pres"],
        well_extension=well_extension,
        ktp_outname=out_name)
    # Header keys are only forwarded when the parsed input carried them so
    # mess_io keeps its own defaults otherwise.
    for key, arg in (
            ("calc_method", "calculation_method"),
            ("model_ene_limit", "model_ene_limit"),
            ("excess_ene_temp", "excess_ene_temp"),
            ("chem_eig_max", "chem_eig_max"),
            ("ene_stepover_temp", "ene_stepover_temp"),
            ("well_red_thresh", "well_reduction_thresh")):
        val = PES_PAYLOAD.get(key)
        if val is not None:
            kwargs[arg] = val
    # PED and microcanonical-rate outputs of this input get names of their
    # own (several inputs run in the same directory).
    stem = out_name
    if stem.endswith(".out"):
        stem = stem[:-len(".out")]
    ped_species = PES_PAYLOAD.get("ped_species")
    if ped_species:
        kwargs["ped_spc_lst"] = list(ped_species)
        kwargs["ped_outname"] = stem + "_ped.out"
    micro_ener = PES_PAYLOAD.get("micro_ener")
    if micro_ener is not None:
        kwargs["micro_out_params"] = tuple(float(v) for v in micro_ener)
        kwargs["ke_outname"] = stem + "_ke.out"
    globkey_str = global_rates_input_v1(**kwargs)
    old = "PressureList[atm]"
    new = "PressureList[" + PRES_UNIT + "]"
    if old not in globkey_str:
        raise RuntimeError(
            "mess_io did not emit the expected " + old + " literal; the "
            "automech driver refuses to write a MESS input with the wrong "
            "pressure unit (the pressure grid is in " + PRES_UNIT + ").")
    return globkey_str.replace(old, new)


def _keep_well_extension(inp_str):
    # Pass 2: mess_io inserts a bare WellExtension line before Model. This
    # PES already carries its own WellExtension value (written in pass 1),
    # so the bare line is dropped and the value is kept.
    lines = inp_str.split("\\n")
    kept = [line for line in lines if line.strip() != "WellExtension"]
    return "\\n".join(kept)


def _run_mess(inp_name):
    subprocess.run(["mess", inp_name], check=False)


def _lump_pressure_atm():
    # mess_io parses the output pressures into atm whatever the unit of the
    # PressureList, so the lump pressure is compared in atm too. Otherwise no
    # k(T) is found there and the WellExtension caps fall back to the
    # lowest temperature of the run.
    if PRES_UNIT == "bar":
        return LUMP_PRESSURE * phycon.BAR2ATM
    if PRES_UNIT == "torr":
        return LUMP_PRESSURE * phycon.TORR2ATM
    return LUMP_PRESSURE


def main():
    base = NAME + "P" + ("%02d" % SLOT)
    inp_name = base + ".inp"
    out_name = base + ".out"
    aux_name = base + ".aux"
    log_name = base + ".log"
    pass1_copy = "_" + base + ".out"

    rxn_chan_str = _rxn_chan_str()
    etrans_str = _energy_transfer_str()

    # Pass 1: the input's own WellExtension value, if any (none otherwise);
    # well_lumped_input_file will add caps.
    globkey_str = _globkey_str(out_name, PES_PAYLOAD.get("well_extension"))
    base_inp = messrates_inp_str(
        globkey_str, rxn_chan_str, energy_trans_str=etrans_str)
    handle = open(inp_name, "w")
    handle.write(base_inp)
    handle.close()

    _run_mess(inp_name)
    if not os.path.isfile(out_name):
        # MESS pass 1 produced no output: clean exit, no pass 2, no rename.
        # The final output stays absent so the job is retried, not picked up.
        print("MESS pass 1 produced no output " + out_name + ", aborting.")
        return
    os.replace(out_name, pass1_copy)

    if MessOutputReader.well_merging(pass1_copy):
        out_str = open(pass1_copy).read()
        aux_str = ""
        if os.path.isfile(aux_name):
            aux_str = open(aux_name).read()
        log_str = ""
        if os.path.isfile(log_name):
            log_str = open(log_name).read()

        extended_inp = well_lumped_input_file(
            base_inp, out_str, aux_str, log_str, _lump_pressure_atm(),
            LUMP_TEMP)
        if PES_PAYLOAD.get("well_extension") is not None:
            extended_inp = _keep_well_extension(extended_inp)
        handle = open(inp_name, "w")
        handle.write(extended_inp)
        handle.close()

        # Pass 2: final SOP-consistent output at <name>P<slot>.out.
        _run_mess(inp_name)
    else:
        # No merged wells: pass 1 is already the final result.
        os.replace(pass1_copy, out_name)


if __name__ == "__main__":
    main()
'''


class AutomechKinWriter:
    """Serialize one PES of a SOP into an automech MESS driver script.

    Mirrors ``MessWriter``'s interface: instantiate with the SOP and a PES id
    (plus optional postprocessing sub-grid), then call ``write(loc, filename)``.
    """

    def __init__(self,
                 sop: SOP,
                 pes_id: int,
                 sub_p: list[float] | None = None,
                 sub_t: list[float] | None = None,
                 settings: dict[str, Any] | None = None) -> None:
        self.sop: SOP = sop
        self.pes_id: int = pes_id
        self.settings: dict[str, Any] = settings or {}
        # Grid: sub-grid override (postprocessing) else the SOP/self grid.
        self.temp: list[float] = list(
            sub_t if sub_t is not None else sop.temp)
        self.pres_bar: list[float] = list(
            sub_p if sub_p is not None else sop.pres)
        self.pres_unit: str = str(getattr(self.sop, 'pres_unit', 'bar'))

    # ---- serialization helpers (main process; SOP objects available) ----

    @staticmethod
    def _geo(struct) -> list[list[Any]]:
        geo: list[list[Any]] = []
        symbols = struct.get_chemical_symbols()
        positions = struct.get_positions()
        for sym, pos in zip(symbols, positions):
            geo.append([sym, float(pos[0]), float(pos[1]), float(pos[2])])
        return geo

    @staticmethod
    def _mass(struct) -> float:
        return float(sum(struct.get_masses()))

    @staticmethod
    def _elec_levels(item) -> list[list[Any]]:
        levels = getattr(item, 'elec_levels', None) or [[0.0, 1]]
        return [[float(lvl[0]), lvl[1]] for lvl in levels]

    @staticmethod
    def _stoich(*structs) -> str:
        compo: dict[str, int] = {}
        for struct in structs:
            for sym in struct.get_chemical_symbols():
                compo[sym] = compo.get(sym, 0) + 1
        return ''.join(f'{sym}{cnt}' for sym, cnt in sorted(compo.items()))

    def _hind_rotors(self, item) -> list[dict[str, Any]]:
        rotors: list[dict[str, Any]] = []
        for hr in item.h_rotors:
            # Only scan-based rotors map to mess_io.rotor_hindered; Fourier
            # rotors carry no explicit potential grid and are skipped.
            if getattr(hr, 'fourier', False):
                continue
            scan = [float(v) for v in hr.scan]
            npot = len(scan)
            if npot == 0:
                continue
            spline_angles = getattr(hr, 'spline_angles', None)
            if spline_angles is not None:
                # Spline rotor: the angles read from the input are written
                # back with the (possibly perturbed) energies.
                potential = [[float(spline_angles[i]), scan[i]]
                             for i in range(npot)]
            else:
                # Angles are ignored by mess_io under
                # potential_form="fourier" (only the energies are emitted),
                # but rotor_hindered still requires a dict-typed potential,
                # so the grid is kept.
                sym = hr.symmetry if hr.symmetry else 1
                step = (360.0 / sym) / npot
                potential = [[i * step, scan[i]] for i in range(npot)]
            tpm = float(hr.ThermalPowerMax)
            rotor: dict[str, Any] = {
                'group': [g - 1 for g in hr.group],
                'axis': [a - 1 for a in hr.axis],
                'symmetry': int(hr.symmetry),
                'potential': potential,
                'therm_pow_max': tpm if tpm > 0 else None,
            }
            if spline_angles is not None:
                rotor['potential_form'] = 'spline'
            geo = getattr(hr, 'geo', None)
            if geo:
                rotor['geo'] = [
                    [row[0], float(row[1]), float(row[2]), float(row[3])]
                    for row in geo]
            rotors.append(rotor)
        return rotors

    def _multi_rotors(self, item) -> list[dict[str, Any]]:
        rotors: list[dict[str, Any]] = []
        for mr in item.m_rotors:
            int_rots: list[dict[str, Any]] = []
            for ir in mr.internal_rot:
                int_rots.append({
                    'group': [g - 1 for g in ir.group],
                    'axis': [a - 1 for a in ir.axis],
                    'symmetry': int(ir.symmetry),
                    'grid_size': int(ir.gridsize),
                    'mass_exp_size': int(ir.mes),
                    'pot_exp_size': int(ir.pes),
                    'hmin': int(ir.hamiltonsizemin),
                    'hmax': int(ir.hamiltonsizemax),
                })
            rotors.append({
                'sym_factor': float(mr.symFact),
                'pot_surf_file': mr.file,
                'interp_emax': float(mr.iem),
                'quant_lvl_emax': float(mr.qlem),
                'int_rots': int_rots,
            })
        return rotors

    def _species_payload(self, item: Well) -> dict[str, Any]:
        # A MESS Atom keeps the Mass[amu] of its input block (mess_io atom).
        mass = self._mass(item.structure)
        atom_mass = getattr(item, 'atom_mass', None)
        if getattr(item, 'is_atom', False) and atom_mass is not None:
            mass = float(atom_mass)
        return {
            'label': item.name,
            'zero_ene': float(item.energy),
            'geo': self._geo(item.structure),
            'mass': mass,
            'sym_factor': float(getattr(item, 'sym_factor', 1.0)),
            'freqs': [float(f) for f in item.frequencies],
            'elec_levels': self._elec_levels(item),
            'hind_rotors': self._hind_rotors(item),
            'multi_rotors': self._multi_rotors(item),
        }

    def _bimol_payload(self, bim: Bimolecular) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'label': bim.name,
            'ground_ene': float(bim.energy),
            'frag1': self._species_payload(bim.fragments[0]),
            'frag2': self._species_payload(bim.fragments[1]),
        }
        # MESS ``density`` keyword of each fragment slot, only when set.
        flags = getattr(bim, 'fragment_density', None) or []
        for slot, key in ((0, 'frag1_density'), (1, 'frag2_density')):
            if slot < len(flags) and flags[slot]:
                payload[key] = True
        return payload

    def _barrier_payload(self, bar: Barrier) -> dict[str, Any] | None:
        reac = bar.connected[0].name
        prod = bar.connected[1].name
        elec = self._elec_levels(bar)
        if not bar.barrierless:
            return {
                'kind': 'saddle',
                'label': bar.name,
                'reac': reac,
                'prod': prod,
                'zero_ene': float(bar.energy),
                'geo': self._geo(bar.structure),
                'sym_factor': float(bar.symFact),
                'freqs': [float(f) for f in bar.frequencies],
                'elec_levels': elec,
                'hind_rotors': self._hind_rotors(bar),
                'ifreq': float(bar.ifreq),
                'well_depth1': float(bar.r_lenergy),
                'well_depth2': float(bar.r_renergy),
            }
        # Barrierless: locate the dissociating bimolecular side to obtain the
        # two fragment geometries and combined stoichiometry.
        bimol_side = next(
            (s for s in bar.connected if isinstance(s, Bimolecular)), None)
        if bimol_side is not None:
            struct1 = bimol_side.fragments[0].structure
            struct2 = bimol_side.fragments[1].structure
        else:
            struct1 = bar.connected[0].structure
            struct2 = bar.connected[1].structure
        stoich = self._stoich(struct1, struct2)
        common = {
            'label': bar.name,
            'reac': reac,
            'prod': prod,
            'zero_ene': float(bar.energy),
            'freqs': [float(f) for f in bar.frequencies],
            'elec_levels': elec,
            'sym_factor': float(bar.symFact),
            'stoich': stoich,
        }
        if hasattr(bar, 'file'):
            common['kind'] = 'rotd'
            common['flux_file'] = bar.file
            common['hind_rotors'] = self._hind_rotors(bar)
            return common
        common['kind'] = 'phasespace'
        common['geo1'] = self._geo(struct1)
        common['geo2'] = self._geo(struct2)
        common['pot_prefactor'] = float(getattr(bar, 'pp', 10.0))
        common['pot_exp'] = float(getattr(bar, 'ppe', 6.0))
        common['hind_rotors'] = self._hind_rotors(bar)
        tst_level = getattr(bar, 'tst_level', None)
        if tst_level:
            # mess_io.core_phasespace expects 'e', 'ej' or 't'.
            common['tst_level'] = str(tst_level).casefold()
        return common

    def _pes_file_data(self) -> PesFileData | None:
        """Data of this PES's input file (None for SOPs without it)."""
        return (getattr(self.sop, 'pes_file_data', None) or {}).get(
            self.pes_id)

    def _collider_pair(self, values: list[float], label: str) -> list[float]:
        """Lennard-Jones pair written for this PES.

        The SOP list holds the collider value first, then one value per
        input file (file k at index k+1): this PES gets
        ``[collider, values[pes_id + 1]]``.

        Args:
            values (list[float]): ``SOP.epsilons`` or ``SOP.sigmas``.
            label (str): 'epsilons' or 'sigmas' (error message).

        Returns:
            list[float]: the pair, or the list unchanged (as floats) when it
            holds fewer than two values.
        """
        floats = [float(v) for v in values]
        if len(floats) < 2:
            return floats
        if len(floats) < self.pes_id + 2:
            raise ValueError(
                f'SOP.{label} holds {len(floats)} values: no value for PES '
                f'{self.pes_id} (expected at index {self.pes_id + 1}).')
        return [floats[0], floats[self.pes_id + 1]]

    def _hardcode_warnings(self) -> None:
        """Warn (once per process) when the inputs set a key that mess_io
        writes with its own hard-coded value in the automech input.

        Checked: this PES's AtomDistanceMin (mess_io: 0.68793 angstrom) and
        the SOP-wide WellCutoff (10), ReductionMethod (diagonalization),
        GroundEnergyShiftMax (10 kcal/mol) and FloatType (double).
        """
        pes_data = self._pes_file_data()
        if pes_data is not None and pes_data.atom_distance_min is not None:
            value, unit = pes_data.atom_distance_min
            in_angstrom = value * _BOHR2ANG if unit == 'bohr' else value
            if abs(in_angstrom - _MESS_IO_ATOM_DISTANCE_MIN) > 1e-6:
                _log_once(
                    f'AtomDistanceMin:{value}:{unit}',
                    f'AtomDistanceMin {value} [{unit}] read from the MESS '
                    'input is not used by the automech driver: mess_io '
                    f'writes AtomDistanceMin {_MESS_IO_ATOM_DISTANCE_MIN} '
                    '[angstrom].')
        for label, attr, mess_io_value in (
                ('WellCutoff', 'well_cutoff', 10.0),
                ('GroundEnergyShiftMax', 'ground_ene_shift_max', 10.0)):
            value = getattr(self.sop, attr, None)
            if value is not None and float(value) != mess_io_value:
                _log_once(
                    f'{label}:{value}',
                    f'{label} {value} read from the MESS inputs is not used '
                    f'by the automech driver: mess_io writes {label} '
                    f'{mess_io_value:g}.')
        for label, attr, mess_io_value in (
                ('ReductionMethod', 'reduction_method', 'diagonalization'),
                ('FloatType', 'float_type', 'double')):
            value = getattr(self.sop, attr, None)
            if value is not None and str(value).casefold() != mess_io_value:
                _log_once(
                    f'{label}:{value}',
                    f'{label} {value} read from the MESS inputs is not used '
                    f'by the automech driver: mess_io writes {label} '
                    f'{mess_io_value}.')

    def _lj_masses(self, wells: list[Well]) -> list[float]:
        """Collider/species masses for collision_frequency.

        The two masses are taken from this PES's own ``Masses[amu]`` line
        (``SOP.pes_file_data[pes_id].masses``) when available, else from the
        SOP-wide ``SOP.masses`` (first file's line). Otherwise the species
        mass falls back to the heaviest well structure and the bath gas to
        N2 (28.0134 amu), and a warning is logged.
        """
        pes_data = self._pes_file_data()
        own = list(pes_data.masses) if pes_data is not None else []
        if len(own) >= 2:
            return [float(own[0]), float(own[1])]
        masses = list(getattr(self.sop, 'masses', []) or [])
        if len(masses) >= 2:
            return [float(masses[0]), float(masses[1])]
        logging.getLogger(__name__).warning(
            'No Masses[amu] line was read from the MESS input; the automech '
            'driver falls back to an N2 bath gas (28.0134 amu) and the '
            'heaviest well mass for the collision frequency.')
        species_mass = 0.0
        for well_item in wells:
            try:
                species_mass = max(species_mass, self._mass(well_item.structure))
            except Exception:
                continue
        if species_mass <= 0.0:
            species_mass = 28.0134
        return [28.0134, species_mass]

    def _build_payload(self) -> dict[str, Any]:
        wells = [w for w in self.sop.wells_in(self.pes_id) if not w.dummy]
        bimols = [b for b in self.sop.bimols_in(self.pes_id) if not b.dummy]
        barriers = [
            bar for bar in self.sop.barriers
            if self.pes_id in bar.pes_ids and not bar.dummy
        ]
        barrier_payloads: list[dict[str, Any]] = []
        for bar in barriers:
            payload = self._barrier_payload(bar)
            if payload is not None:
                barrier_payloads.append(payload)
        grid_pres = [float(p) for p in self.pres_bar]
        pes_data = self._pes_file_data()
        self._hardcode_warnings()
        # ModelEnergyLimit is PES-specific: this file's own value (None:
        # mess_io's default), SOP-wide value for SOPs without file data.
        if pes_data is not None:
            model_ene_limit = pes_data.model_ene_limit
        else:
            model_ene_limit = getattr(self.sop, 'model_ene_limit', None)
        excess_ene_temp = getattr(self.sop, 'excess_ene_temp', None)
        chem_eig_max = getattr(self.sop, 'chem_eig_max', None)
        exp_cutoff = getattr(self.sop, 'exp_cutoff', None)
        payload: dict[str, Any] = {
            'name': f'{self.pes_id:02d}',
            'calc_method': getattr(self.sop, 'calculation_method', None),
            'model_ene_limit': (
                float(model_ene_limit) if model_ene_limit is not None
                else None),
            'excess_ene_temp': (
                float(excess_ene_temp) if excess_ene_temp is not None
                else None),
            'chem_eig_max': (
                float(chem_eig_max) if chem_eig_max is not None else None),
            'factor': float(getattr(self.sop, 'factor', 0.0)),
            'power': float(getattr(self.sop, 'power', 0.0)),
            'epsilons': self._collider_pair(self.sop.epsilons, 'epsilons'),
            'sigmas': self._collider_pair(self.sop.sigmas, 'sigmas'),
            'lj_masses': self._lj_masses(wells),
            'edown_cutoff': (
                float(exp_cutoff) if exp_cutoff is not None else 15.0),
            'grid_temp': [float(t) for t in self.temp],
            'grid_pres': grid_pres,
            'wells': [self._species_payload(w) for w in wells],
            'bimols': [self._bimol_payload(b) for b in bimols],
            'barriers': barrier_payloads,
        }
        # Optional keys, only when the inputs carry them (mess_io keeps its
        # own defaults otherwise).
        for key, value in (
                ('ene_stepover_temp',
                 getattr(self.sop, 'ene_step_over_temp', None)),
                ('well_red_thresh',
                 getattr(self.sop, 'well_reduction_threshold', None))):
            if value is not None:
                payload[key] = float(value)
        if pes_data is not None:
            self._add_file_keys(payload, pes_data)
        return payload

    def _add_file_keys(self,
                       payload: dict[str, Any],
                       pes_data: PesFileData) -> None:
        """Add this PES's own input-file data to the payload.

        Energies are shifted back to the energy zero of the PES's input file;
        WellExtension, PEDSpecies and MicroEnerMin/Max/Step are added only
        when the file carries them.

        Args:
            payload (dict[str, Any]): payload being built (modified).
            pes_data (PesFileData): this PES's input-file data.
        """
        offset = float(pes_data.energy_offset)
        if offset != 0.0:
            # Rounded to 1e-10 kcal/mol to drop float artefacts of the shift
            for well_payload in payload['wells']:
                well_payload['zero_ene'] = round(
                    well_payload['zero_ene'] + offset, 10)
            for bimol_payload in payload['bimols']:
                bimol_payload['ground_ene'] = round(
                    bimol_payload['ground_ene'] + offset, 10)
            for bar_payload in payload['barriers']:
                bar_payload['zero_ene'] = round(
                    bar_payload['zero_ene'] + offset, 10)
        if pes_data.well_extension is not None:
            payload['well_extension'] = float(pes_data.well_extension)
        if pes_data.ped_species is not None:
            payload['ped_species'] = list(pes_data.ped_species)
        micro_ener = pes_data.micro_ener
        if micro_ener is not None:
            if all(value is not None for value in micro_ener):
                payload['micro_ener'] = [float(v) for v in micro_ener]
            else:
                _log_once(
                    f'micro_ener:{self.pes_id}',
                    'MicroEnerMin/MicroEnerMax/MicroEnerStep are not all '
                    f'set in the MESS input of PES {self.pes_id}: the '
                    'automech driver writes no microcanonical rate output.')

    def write(self,
              loc: str,
              filename: str) -> None:
        payload = self._build_payload()
        grid_temp = payload['grid_temp']
        grid_pres = payload['grid_pres']
        lump_temp = max(grid_temp) if grid_temp else 1000.0
        lump_pressure = max(grid_pres) if grid_pres else 1.0
        # Slot index is encoded in the filename by the caller; parse it back so
        # the emitted script self-labels its output identically.
        slot = 0
        stem = filename
        if 'P' in stem:
            tail = stem.rsplit('P', 1)[1]
            digits = tail.split('.', 1)[0]
            if digits.isdigit():
                slot = int(digits)
        name = stem.rsplit('P', 1)[0] if 'P' in stem else stem.split('.')[0]

        script = automech_kin_tpl.format(
            payload=repr(payload),
            name=name,
            slot=slot,
            pres_unit=self.pres_unit,
            lump_pressure=repr(lump_pressure),
            lump_temp=repr(lump_temp),
        )
        with open(loc + '/' + filename, 'w') as f:
            f.write(script)
