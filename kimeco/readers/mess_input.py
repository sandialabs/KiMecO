from curses.ascii import isdigit
from uu import Error

from kimeco.parameters import SOP
from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.rotors.internalrotation import InternalRotation
from kimeco.logger_config import KMOLogger

import os


# TODO: Make the parsing robust to file swap on
# restart regarding shifted energies

class MessInputReader:
    """Class that read a mess input file and transforms it into
     an object with easily extractable data."""
    def __init__(self,
                 settings: dict,
                 mechanism_species: list[str],
                 klog: KMOLogger,
                 postprocess: bool = False) -> None:
        """Save the file content as a string for further manipulation

        Args:
            settings (dict): Content of the input file
                             with additional default parameters
        """
        self.filenames: list[str] = []
        for mess_input in settings['mess_inputs']:
            self.filenames.append(settings['init_loc'] + '/' + mess_input)
        n_exp = settings.get('n_exp')
        if n_exp is None:
            n_exp = len(settings.get('experiments', []))
        if n_exp <= 0:
            n_exp = 1
        score_keys = [f'exp_{i}' for i in range(n_exp)]
        self.SOP: SOP = SOP(
            score_species=score_keys,
            freq_mode=settings['freq_mode']
        )
        if postprocess:
            self.SOP.temp = settings["pp_temp"]
            self.SOP.pres = settings["pp_pres"]
        else:
            self.SOP.temp = settings["rc_temp"]
            self.SOP.pres = settings["rc_pres"]
        self.SOP.pres_unit = settings["pres_unit"]
        self.klog: KMOLogger = klog
        self.mechanism_species: set[str] = set(mechanism_species)
        self.force_new_molecules: bool = settings['force_new_molecules']
        self.files2copy: list[str] = []
        self.pes_files: list[list[str]] = []
        self.dE: dict[tuple[int, int], float] = {}
        for filename in self.filenames:
            if os.path.isfile(path=filename):
                with open(file=filename, mode='r') as f:
                    self.pes_files.append(f.readlines())
            else:
                raise FileNotFoundError(
                    f'Mess input file {filename} not found.'
                )

        self.tpls: list[list[str]] = []
        # Set to true if a species from MESS input is not present
        # in the mechanism file and 'force_new_molecules' is False,
        # to trigger the stop of the program after reading the input file.
        self._trigger_stop = False

    def validate_species(self,
                         species: str,
                         species_type: str) -> None:
        if species in self.mechanism_species:
            return
        msg: str = (
            f"{species_type} '{species}' from MESS input is not present "
            "in the mechanism file."
        )
        self.klog.warning(msg)
        if not self.force_new_molecules:
            err = (
                f"{msg} Set 'force_new_molecules' to true to continue "
                "with species from MESS input."
            )
            self.klog.error(err)
            self._trigger_stop = True

    def read(self) -> tuple[SOP, list[list[str]]]:
        """Reads a mess input file and transforms it into a
        SetOfParameter object and a mess_template file.

        Returns:
            list[SOP, list[list[str]]]:
            [SetOfParameters, mess_templates]
        """
        name = ''
        skip = 0
        for fid, file in enumerate(self.pes_files):
            self.tpls.append([])
            tpl: list[str] = self.tpls[-1]
            for lnum, line in enumerate(file):

                # Avoid writing data in template
                if skip:
                    skip -= 1
                    continue

                # General parameters

                if line.lstrip().casefold().startswith('temperaturelist'):
                    # self.save_temperatures(lnum=lnum)
                    tpl.append(line.split()[0] + " {SOP.r_rc_temp}\n")
                    continue
                elif line.lstrip().casefold().startswith('pressurelist'):
                    # self.save_pressures(lnum=lnum)
                    tpl.append(
                        "PressureList[{SOP.pres_unit}] {SOP.r_rc_pres}\n")
                    continue
                elif line.lstrip().casefold().startswith('factor'):
                    if not hasattr(self.SOP, "factor"):
                        self.SOP.factor = float(line.split()[1])
                    else:
                        if self.SOP.factor != float(line.split()[1]):
                            self.klog.warning(
                                f"Different factor in {self.filenames[fid]}.\
                                Using the first one encountered: "
                                f"{self.SOP.factor}."
                            )
                            self._trigger_stop = True
                    tpl.append(line.split()[0] + " {SOP.factor}\n")
                    continue
                elif line.lstrip().casefold().startswith('power'):
                    if not hasattr(self.SOP, "power"):
                        self.SOP.power = float(line.split()[1])
                    else:
                        if self.SOP.power != float(line.split()[1]):
                            msg = f"Different power in {self.filenames[fid]}."
                            msg += "\n"
                            msg += f" Saved value: {self.SOP.power}."
                            self.klog.warning(msg)
                            self._trigger_stop = True
                    tpl.append(line.split()[0] + " {SOP.power}\n")
                    continue
                elif line.lstrip().casefold().startswith('epsilons'):
                    tpl.append(
                        line.split()[0] + " {SOP.r_epsilons}\n")
                    if len(self.SOP.epsilons) == 0:
                        for arg in line.split()[1:]:
                            # Avoid reading comments
                            if arg.replace('.', ''
                                           ).replace('-', ''
                                                     ).isnumeric():
                                self.SOP.epsilons.append(float(arg))
                            else:
                                break
                    else:
                        for eps_idx, arg in enumerate(line.split()[1:]):
                            # Avoid reading comments
                            if arg.replace('.', ''
                                           ).replace('-', ''
                                                     ).isnumeric():
                                if eps_idx == 0 and \
                                   float(arg) != self.SOP.epsilons[eps_idx]:
                                    msg = f"Different epsilon {eps_idx}"
                                    msg += f"in {self.filenames[fid]}."
                                    msg += "\n"
                                    msg += " Saved value:"
                                    msg += f" {self.SOP.epsilons[eps_idx]}."
                                    self.klog.warning(msg)
                                    self._trigger_stop = True
                            else:
                                break
                    continue
                elif line.lstrip().casefold().startswith('sigmas'):
                    tpl.append(line.split()[0] + " {SOP.r_sigmas}\n")
                    if len(self.SOP.sigmas) == 0:
                        for arg in line.split()[1:]:
                            # Avoid reading comments
                            if arg.replace('.', ''
                                           ).replace('-', ''
                                                     ).isnumeric():
                                self.SOP.sigmas.append(float(arg))
                            else:
                                break
                    else:
                        for sig_idx, arg in enumerate(line.split()[1:]):
                            # Avoid reading comments
                            if arg.replace('.', ''
                                           ).replace('-', ''
                                                     ).isnumeric():
                                if sig_idx == 0 and \
                                   float(arg) != self.SOP.sigmas[sig_idx]:
                                    msg = f"Different sigma {sig_idx}"
                                    msg += f"in {self.filenames[fid]}."
                                    msg += "\n"
                                    msg += " Saved value:"
                                    msg += f" {self.SOP.sigmas[sig_idx]}."
                                    self.klog.warning(msg)
                                    self._trigger_stop = True
                            else:
                                break
                    continue

                # Set the name of the current item

                # WELL
                elif (line.lstrip().casefold().startswith('well') and
                      line.lstrip().casefold().split()[0] == 'well'):
                    last_item = 'well'
                    name: str = line.split()[1]
                    if name not in self.SOP.items:
                        self.validate_species(species=name,
                                              species_type='Well')
                        self.SOP.add_new_well(name=name,
                                              pes_id=fid)
                    else:
                        error: bool = self.SOP.check_well(
                            name=name,
                            pes_id=fid)
                        if error:
                            msg = f"Well {name} already exists."
                            self.klog.warning(msg)
                            self._trigger_stop = True
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{name}.name" \
                        + "}\n"
                    tpl.append(new_line)
                    continue
                # BIMOLECULAR
                elif line.lstrip().casefold().startswith('bimolecular'):
                    last_item = 'bimo'
                    name: str = line.split()[1]
                    if name not in self.SOP.items:
                        self.SOP.add_new_bimol(name=name,
                                               pes_id=fid)
                    else:
                        if fid in self.SOP.items[name].pes_ids:
                            msg: str = f"Multiple Bimolecular {name} exist"
                            msg += f" in {self.filenames[fid]}."
                            self.klog.warning(msg)
                            self._trigger_stop = True
                        else:
                            self.SOP.add_new_bimol(name=name,
                                                   pes_id=fid)
                            initial_file: int = self.SOP.items[name].pes_ids[0]
                            msg: str = f"Bimolecular {name} already exists"
                            msg += f" in { self.filenames[initial_file]}."
                            self.klog.warning(msg)
                            self.dE[(initial_file, fid)] = 0.0
                        # self._trigger_stop = True
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{name}.name" \
                        + "}\n"
                    tpl.append(new_line)
                    continue
                # BARRIER
                elif line.lstrip().casefold().startswith('barrier'):
                    last_item = 'barr'
                    tokens = line.split()[1:4]
                    if len(tokens) < 3:
                        err = (
                            f"Malformed BARRIER directive in {self.filenames[fid]} "
                            f"at line {lnum + 1}.\n"
                            f"Expected: Barrier <name> <left_side> <right_side>\n"
                            f"Got: {line.rstrip()}\n"
                            f"Only {len(tokens)} token(s) found: {tokens}"
                        )
                        self.klog.error(err)
                        self._trigger_stop = True
                        continue
                    name, lside, rside = tokens
                    if name not in self.SOP.items:
                        self.SOP.add_new_barrier(name=name,
                                                 lside=lside,
                                                 rside=rside,
                                                 pes_id=fid)
                    else:
                        msg = f"Barrier {name} already exists"
                        msg += f" in {self.filenames[self.SOP.items[name].pes_ids[0]]}."
                        msg += " Duplicate barriers across input files are not allowed."
                        self.klog.warning(msg)
                        self._trigger_stop = True
                    new_line: str = line.split()[0]
                    new_line += " {" + f"{name}.name" + "}"
                    new_line += " {" + f"{lside}.name" + "}"
                    new_line += " {" + f"{rside}.name" + "}\n"
                    tpl.append(new_line)
                    continue
                # Different types of barrierless
                elif (line.lstrip().casefold().startswith('core')
                      and
                      line.lstrip().casefold().split()[1] == 'phasespacetheory'
                      and
                      isinstance(self.SOP.items[name], Barrier)):
                    self.SOP.items[name].barrierless = True
                    tpl.append(line)
                    skip += self.save_phasespacetheory(name, lnum)
                    continue
                elif (line.lstrip().casefold().startswith('core')
                      and line.lstrip().casefold().split()[1] == 'rotd'
                      and isinstance(self.SOP.items[name], Barrier)):
                    self.SOP.items[name].barrierless = True
                    tpl.append(line)
                    skip += self.save_rotd(name, lnum)
                    continue
                # FRAGMENT
                elif line.lstrip().casefold().startswith('fragment')\
                        and 'geom' not in line.casefold():
                    last_item = 'frag'
                    fname: str = line.split()[1]
                    if isinstance(self.SOP.items[name], Bimolecular):
                        if len(self.SOP.items[name].fragments) < 2:
                            if fname not in self.SOP.items[name].frag_names:
                                self.validate_species(
                                    species=fname,
                                    species_type='Fragment')
                                if fname not in self.SOP.items:
                                    # Fragments don't get a pes_id because
                                    # they are not part of
                                    # the same pes as the bimol
                                    self.SOP.items[name].add_new_frag(fname)
                                    self.SOP.items[fname] = \
                                        self.SOP.items[name].fragments[-1]
                                else:
                                    self.SOP.items[name].fragments.append(
                                        self.SOP.items[fname])
                            # if the bimol has twice the same fragment,
                            # don't recreate the object
                            else:
                                self.SOP.items[name].fragments.append(
                                    self.SOP.items[name].fragments[0])
                        else:
                            self.klog.warning(
                                f"Bimol{name} already has two fragments. "
                                f"Cannot add fragment {fname}.")
                            self._trigger_stop = True
                    else:
                        msg = f"Cannot add a fragment to non-bimol {name}."
                        msg += "\n"
                        msg += f"Error in {self.filenames[fid]}."
                        self.klog.warning(msg=msg)
                        self._trigger_stop = True
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{fname}.name" \
                        + "}\n"
                    tpl.append(new_line)
                    continue

                # Dummy
                elif line.lstrip().casefold().startswith('dummy'):
                    tpl.append(line)
                    self.SOP.items[name].dummy = True
                    continue

                # Add parameters to items

                # GEOMETRY
                elif line.lstrip().casefold().startswith('geometry')\
                        and 'rotor' not in file[lnum-1].casefold():
                    natom = int(line.split()[1])
                    tpl.append(line)
                    if last_item == 'frag':
                        self.save_geom(
                            fname,
                            lnum,
                            natom)
                    else:
                        self.save_geom(
                            name,
                            lnum,
                            natom)
                    continue
                elif line.lstrip().casefold().startswith('fragmentgeometry'):
                    natom = int(line.split()[1])
                    tpl.append(line)
                    self.save_geom(fname, lnum, natom)
                    continue

                # FREQUENCIES
                elif line.lstrip().casefold().startswith('frequencies'):
                    nfreq = int(line.split()[1])
                    tpl.append(line)
                    if last_item == 'frag':
                        nlines: int = self.save_freq(name=fname,
                                                     lnum=lnum,
                                                     nfreq=nfreq)
                    else:
                        nlines: int = self.save_freq(name=name,
                                                     lnum=lnum,
                                                     nfreq=nfreq)
                    skip += nlines
                    continue

                # HINDERED ROTOR
                elif line.lstrip().casefold().startswith('rotor') and\
                        line.split()[1].casefold() == 'hindered':
                    tpl.append(line)
                    if last_item == 'frag':
                        skip += self.save_rotor(name=fname,
                                                lnum=lnum)
                    else:
                        skip += self.save_rotor(name=name,
                                                lnum=lnum)
                    continue

                # MULTI ROTOR
                elif (line.lstrip().casefold().startswith('core') and
                      line.split()[1].casefold() == 'multirotor'):
                    tpl.append(line)
                    if last_item == 'frag':
                        skip += self.save_multirotor(name=fname,
                                                     lnum=lnum)
                    else:
                        skip += self.save_multirotor(name=name,
                                                     lnum=lnum)
                    continue

                # ENERGY
                elif line.lstrip().casefold().startswith('zeroenergy'):
                    energy = float(line.split()[1])
                    if last_item == 'frag':
                        self.save_energy(name=fname,
                                         energy=energy,
                                         lnum=lnum,
                                         frag=True)
                    else:
                        self.save_energy(name=name,
                                         energy=energy,
                                         lnum=lnum)
                    continue
                elif line.lstrip().casefold().startswith('groundenergy'):
                    # for bimolec
                    energy = float(line.split()[1])
                    first_pes_id = self.SOP.items[name].pes_ids[0]
                    shift_key = (first_pes_id, fid)
                    if shift_key in self.dE:
                        shift: float = self.dE[shift_key]
                        current_shift = self.SOP.items[name].energy - energy
                        if shift == 0.0:
                            # Save the shift between PESs
                            self.dE[shift_key] = current_shift
                        # If a shift was already saved,
                        # check that it's consistent with the current one
                        elif shift != current_shift:
                            msg = "Inconsistent energy shift for "
                            msg += f"{name} in {self.filenames[fid]}."
                            msg += "\n"
                            msg += f"Previous shift: {self.dE[shift_key]}"
                            msg += f" Current shift: {current_shift}"
                            self.klog.warning(msg)
                            self._trigger_stop = True

                    self.save_energy(name=name,
                                     energy=energy,
                                     lnum=lnum)
                    continue

                # TUNNELING
                elif line.lstrip().casefold().startswith('tunneling'):
                    tun_type = str(line.split()[1])
                    tpl.append(line)
                    skip += self.save_tunneling(name=name,
                                                tun_type=tun_type,
                                                lnum=lnum)
                    continue

                # All other lines
                else:
                    tpl.append(line)

        for bar in self.SOP.barriers:
            for well_idx in range(len(bar.connected)):
                # Set the enegy of dummies from tunneling logic
                if bar.connected[well_idx].dummy:
                    bar.connected[well_idx]._energy = \
                        bar.energy - bar._well_depth[well_idx]
        self.shift_PESs()
        self.SOP.files2copy = self.files2copy
        return (self.SOP, self.tpls)

    def shift_PESs(self) -> None:
        """Shift the energies of species in different
        PESs if needed, to be able
        to compare them and use them together in the same mechanism.
        """
        for (pes1, pes2), shift in self.dE.items():
            if shift != 0.0:
                for item in self.SOP.items.values():
                    if pes2 in item.pes_ids:
                        item._energy -= shift
                msg: str = f"Shifted energies of PES {self.filenames[pes2]} by"
                msg += f" {shift} to match PES {self.filenames[pes1]}."
                self.klog.info(msg)

    def save_phasespacetheory(self,
                              name: str,
                              lnum: int) -> int:
        """Save the barierless parameters in case of a phasespacetheory core

        Args:
            name (str): name of the barrier
            lnum (int): line number from wich to record this core

        Returns:
            int: number of line to skip to not double read this core
        """
        bar: Barrier = self.SOP.items[name]
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        tpl = self.tpls[-1]

        # Read the file
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                tpl.append(new_line)
            elif line.lstrip().casefold().startswith('potentialprefactor'):
                bar.pp = float(line.split()[1])
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('potentialpowerexponent'):
                bar.ppe = float(line.split()[1])
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                tpl.append(line)
        raise Error(f'Incorrect termination of phasespacetheory core for {name}')

    def save_rotd(self,
                  name: str,
                  lnum: int) -> int:
        """Save the barierless parameters in case of a rotd core

        Args:
            name (str): name of the barrier
            lnum (int): line number from wich to record this core

        Returns:
            int: number of line to skip to not double read this core
        """
        bar: Barrier = self.SOP.items[name]
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        tpl: list[str] = self.tpls[-1]
        # Read the file
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                tpl.append(new_line)
            elif line.lstrip().casefold().startswith('file'):
                bar.file = line.split()[1]
                if bar.file not in self.files2copy:
                    self.files2copy.append(bar.file)
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                tpl.append(line)
        raise Error(f'Incorrect termination of rotd core for {name}')

    def save_temperatures(self, lnum: int) -> None:
        """Save temperatures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """

        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        if self.SOP.temp == []:
            args: list[str] = file[lnum].split()
            temp_list: list = []
            arg_n = 1
            # There should be no negative numbers in the list
            while arg_n < len(args) and\
                    args[arg_n].replace(".", "")\
                               .isnumeric():
                temp_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.temp = temp_list

    def save_pressures(self, lnum: int) -> None:
        """Save pressures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        if self.SOP.pres == []:
            args: list[str] = file[lnum].split()
            pres_list: list = []
            arg_n = 1
            # There should be no negative numbers in the list
            while arg_n < len(args) and\
                    args[arg_n].replace(".", "")\
                               .isnumeric():
                pres_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.pres = pres_list

    def save_freq(self,
                  name: str,
                  lnum: int,
                  nfreq: int) -> int:
        """Save the next frequencies encountered in Mess in
        the item name.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file
            nfreq (int): Number of frequencies to record

        Raises:
            TypeError: inconsistent number of freq

        Returns:
            int: number of line to skip readinding in the read method.
        """
        freqs: list = []
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for lnum2, line in enumerate(file[lnum+1:]):
            args: list[str] = line.split()
            arg_n = 0
            while arg_n < len(args) and args[arg_n].replace(".",
                                                            "").isnumeric():
                freqs.append(float(args[arg_n]))
                arg_n += 1
            if len(freqs) == nfreq:
                self.SOP.set_freqs(name, freqs)
                new_line: str = " {" + f"{name}" + ".r_freq}\n"
                self.tpls[-1].append(new_line)
                return lnum2+1
            if lnum2 > nfreq:
                msg: str = f"Error in {self.filenames[fid]}:"
                msg += "\n"
                msg += f"wrong number of frequencies for {name}."
                raise TypeError(msg)
        return 0

    def save_rotor(self,
                   name: str,
                   lnum: int) -> int:
        """Save the next hindered rotor encountered in Mess in
        the last structure dictionary.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file

        Raises:
            TypeError: error in input file
            TypeError: error in input file
            TypeError: error in input file
            Error: unknown error

        Returns:
            int: number of line to skip readinding in the read method.
        """

        # default
        thermalpowermax = 0.0
        scan: list[float] = []
        fexp: list[int] = []
        fcoef: list[float] = []
        npot: int = 0
        skip: int = 0
        symmetry: int = 0
        local_skip: int = 0
        rot_num: int = len(self.SOP.items[name].h_rotors)
        saved_f: int = 0
        group: list[int] = []
        axis: list[int] = []
        # Read the file
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for lnum2, line in enumerate(file[lnum+1:]):
            stripped = line.lstrip()
            # SCAN
            if local_skip:
                local_skip -= 1
                self.tpls[-1].append(line)
                continue

            if line.lstrip().casefold().startswith('potential'):
                npot = int(line.split()[1])
                self.tpls[-1].append(line)
                new_line: str = " {" \
                    + f"{name}" \
                    + ".r_scan" \
                    + f"({rot_num})" \
                    + "}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                saved_f = 0
                continue
            elif npot != 0 and saved_f < npot:
                args: list[str] = line.split()
                arg_n = 0
                while (arg_n < len(args) and
                       args[arg_n].replace(".", "").replace("-", "")
                                                   .isnumeric()):
                    scan.append(float(args[arg_n]))
                    arg_n += 1
                    saved_f += 1
                if saved_f > npot:
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('fourierexpansion'):
                self.tpls[-1].append(line)
                nexp = int(line.split()[1])
                abs_idx = lnum + 1 + lnum2
                fexp = [
                    int(exp_line.split()[0])
                    for exp_line in file[abs_idx+1:abs_idx+1+nexp]]
                fcoef = [
                    float(exp_line.split()[1])
                    for exp_line in file[abs_idx+1:abs_idx+1+nexp]]
                for li in file[abs_idx+1:abs_idx+1+nexp]:
                    self.tpls[-1].append(li)
                skip += 1 + nexp
                continue

            # Other keys
            elif line.lstrip().casefold().startswith('thermalpowermax'):
                thermalpowermax = float(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('group'):
                group: list[int] = []
                for nmbr in line.split()[1:]:
                    if nmbr.lstrip('+-').isdigit():
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis: list[int] = []
                for nmbr in line.split()[1:]:
                    if nmbr.lstrip('+-').isdigit():
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('geometry'):
                local_skip += int(line.split()[1])
                skip += int(line.split()[1]) + 1
                self.tpls[-1].append(line)
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            # END
            elif line.lstrip().casefold().startswith('end'):
                if saved_f != npot:
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                self.SOP.set_hrotor(
                    name=name,
                    thermalpowermax=thermalpowermax,
                    group=group,
                    axis=axis,
                    symmetry=symmetry,
                    scan=scan,
                    fexp=fexp,
                    fcoef=fcoef)
                self.tpls[-1].append(line)
                skip += 1
                return skip
            elif line.strip() == '' or stripped.startswith(('#', '!', '+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue
            else:
                raise Error(f'Incorrect termination of rotor for {name}')
        return 0

    def save_multirotor(self,
                        name: str,
                        lnum: int) -> int:
        """Save the next hindered rotor encountered in Mess in
        the last structure dictionary.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file

        Raises:
            TypeError: error in input file
            TypeError: error in input file
            TypeError: error in input file
            Error: unknown error

        Returns:
            int: number of line to skip readinding in the read method.
        """

        skip = 0
        rot_idx = len(self.SOP.items[name].m_rotors)
        irs: list[InternalRotation] = []
        ir_skip: int = 0
        sf: float | None = None
        iem: float | None = None
        pes: str | None = None
        qlem: float | None = None
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]

        for lnum2, line in enumerate(file[lnum+1:]):
            lower_line = line.lstrip().casefold()
            is_blank = line.strip() == ''
            # Skip through the lines of internal rotation
            if ir_skip != 0:
                ir_skip -= 1
                continue
            # SymmetryFactor
            if lower_line.startswith('symmetryfactor'):
                sf = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".symFact}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # InterpolationEnergyMax
            elif lower_line.startswith('interpolationenergymax'):
                iem = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".iem}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # PotentialEnergySurface
            elif lower_line.startswith('potentialenergysurface'):
                pes = line.split()[1]
                if pes not in self.files2copy:
                    self.files2copy.append(pes)
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".file}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # QuantumLevelEnergyMax
            elif lower_line.startswith('quantumlevelenergymax'):
                qlem = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".qlem}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # InternalRotation
            elif lower_line.startswith('internalrotation'):
                self.tpls[-1].append(line)
                skip += 1
                ir_skip, ir = self.create_internal_rotation(
                    name=name,
                    lnum=lnum2+lnum+1)
                irs.append(ir)
                skip += ir_skip
                continue
            # END
            elif lower_line.startswith('end'):
                missing: list[str] = []
                if sf is None:
                    missing.append('SymmetryFactor')
                if iem is None:
                    missing.append('InterpolationEnergyMax')
                if pes is None:
                    missing.append('PotentialEnergySurface')
                if qlem is None:
                    missing.append('QuantumLevelEnergyMax')
                if missing:
                    miss = ', '.join(missing)
                    raise TypeError(
                        f"Missing MultiRotor keyword(s) for {name}: {miss}"
                    )
                assert sf is not None
                assert iem is not None
                assert pes is not None
                assert qlem is not None
                self.SOP.set_mrotor(
                    name=name,
                    sf=sf,
                    iem=iem,
                    pes=pes,
                    qlem=qlem,
                    irs=irs
                )
                self.tpls[-1].append(line)
                skip += 1
                return skip
            elif is_blank or lower_line.startswith(('#', '!', '+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue  # ignore comments
            else:
                raise Error(f'Incorrect termination of rotor for {name}')
        return 0

    def create_internal_rotation(self,
                                 name: str,
                                 lnum: int):
        """Create an InternalRotation Object

        Args:
            name (str): name of the SOP item
            lnum (int): line number to start to read after

        Raises:
            TypeError: not int in group
            TypeError: not int in axis
            AttributeError: unknown attribute

        Returns:
            tuple(int, InternalRotation):
                int: lines to skip
                ir object to be added to MultiRotor
        """
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        group: list[int] | None = None
        axis: list[int] | None = None
        symmetry: int | None = None
        mes: int | None = None
        pes: int | None = None
        hamiltonsizemin: int | None = None
        hamiltonsizemax: int | None = None
        gridsize: int | None = None
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('group'):
                group = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('massexpansionsize'):
                mes = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('potentialexpansionsize'):
                pes = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemin'):
                hamiltonsizemin = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemax'):
                hamiltonsizemax = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('gridsize'):
                gridsize = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('end'):
                missing: list[str] = []
                if group is None:
                    missing.append('Group')
                if axis is None:
                    missing.append('Axis')
                if symmetry is None:
                    missing.append('Symmetry')
                if mes is None:
                    missing.append('MassExpansionSize')
                if pes is None:
                    missing.append('PotentialExpansionSize')
                if hamiltonsizemin is None:
                    missing.append('HamiltonSizeMin')
                if hamiltonsizemax is None:
                    missing.append('HamiltonSizeMax')
                if gridsize is None:
                    missing.append('GridSize')
                if missing:
                    miss = ', '.join(missing)
                    msg = "Missing InternalRotation keyword(s) "
                    msg += f"for {name}: {miss}"
                    raise TypeError(
                        msg
                    )
                assert group is not None
                assert axis is not None
                assert symmetry is not None
                assert mes is not None
                assert pes is not None
                assert hamiltonsizemin is not None
                assert hamiltonsizemax is not None
                assert gridsize is not None
                ir = InternalRotation(
                    group=group,
                    axis=axis,
                    symmetry=symmetry,
                    massexpansionsize=mes,
                    potentialexpansionsize=pes,
                    hamiltonsizemax=hamiltonsizemax,
                    hamiltonsizemin=hamiltonsizemin,
                    gridsize=gridsize
                )
                self.tpls[-1].append(line)
                skip += 1
                return (skip, ir)
            elif (line.lstrip().startswith('#') or
                  line.lstrip().startswith('!') or
                  line.strip() == '' or
                  line.lstrip().startswith('+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue
            else:
                raise AttributeError('Unknown keyword for InternalRotation')
        raise Error(f'Incorrect termination of internalrotation for {name}')

    def save_geom(self,
                  name: str,
                  lnum: int,
                  natom: int) -> None:
        """Save the geometry of the object 'name'
        in the SOP object.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file
            natom (int): Number of atoms in the geometry
            fid (int): File ID
        """
        symbols: list[str] = []
        geom: list = []
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for idx, line in enumerate(file[lnum+1:lnum+natom+1], start=lnum+1):
            tokens = line.split()
            if len(tokens) < 4:
                err = (
                    f"Malformed geometry line in {self.filenames[-1]} "
                    f"at line {idx + 1}.\n"
                    f"Expected at least: <symbol> <x> <y> <z>\n"
                    f"Got: {line.rstrip()}\n"
                    f"Only {len(tokens)} token(s) found: {tokens}"
                )
                self.klog.error(err)
                self._trigger_stop = True
                break
            symbols.append(tokens[0])
            try:
                x, y, z = tokens[1:4]
                geom.append([float(x), float(y), float(z)])
            except ValueError:
                err = (
                    f"Invalid coordinate values in {self.filenames[-1]} "
                    f"at line {idx + 1}.\n"
                    f"Expected numbers for x, y, z but got: {tokens[1:4]}\n"
                    f"Full line: {line.rstrip()}"
                )
                self.klog.error(err)
                self._trigger_stop = True
                break

        self.SOP.set_structure(
            name,
            symbols,
            geom,
            self.klog)

    def save_energy(self,
                    name: str,
                    energy: float,
                    lnum: int,
                    frag=False) -> None:
        """Save the energy of the object 'name'
        in the SOP object.

        Args:
            name (str): Object's (well, bimol, barrier) name
            energy (float): Energy of the object in (kcal/mol)
            lnum (int): Line number in input file
        """
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        if isinstance(self.SOP.items[name], Barrier):
            self.SOP.items[name]._energy = energy
        else:
            # Do not change the energy of a specie
            # if it is encountered as a frag
            if not frag:
                self.SOP.items[name]._energy = energy
        if not frag:
            new_line: str = f"{file[lnum].split()[0]}" \
                            + " {" + f"{name}" \
                            + ".energy}\n"
            self.tpls[-1].append(new_line)
        else:
            self.tpls[-1].append(file[lnum])


    def save_tunneling(self,
                       name: str,
                       tun_type: str,
                       lnum: int) -> int:
        """Save the imaginary freq for tunneling and check left/right energies.

        Args:
            name (str): Object's (well, bimol, barrier) name
            tun_type (str): Type of tunneling - for future development
            lnum (int): Line number in input file

        Returns:
            int: number of line to skip readinding in the read method.
        """
        well_depth: list[float] = [-1.0, -1.0]
        bar: Barrier = self.SOP.items[name]
        well_idx = 0
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for line in file[lnum+1:]:
            if line.lstrip().casefold().startswith('imaginaryfrequency'):
                ifreq = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".ifreq}\n"
                bar.ifreq = ifreq
                self.tpls[-1].append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('cutoffenergy'):
                # coff = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".r_coff}\n"
                self.tpls[-1].append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('welldepth'):
                well_depth[well_idx] = float(line.split()[1])
                if well_idx == 0:
                    new_line: str = f"{line.split()[0]}" \
                        + " {" \
                        + f"{name}" \
                        + ".r_lenergy}\n"
                elif well_idx == 1:
                    new_line: str = f"{line.split()[0]}" \
                        + " {" \
                        + f"{name}" \
                        + ".r_renergy}\n"
                bar._well_depth = well_depth
                self.tpls[-1].append(new_line)
                well_idx += 1
                skip += 1
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                self.tpls[-1].append(line)
                skip += 1
