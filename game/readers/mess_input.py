from curses.ascii import isdigit
from uu import Error

from game.parameters import SOP
from game.barrier import Barrier

import os


class MessInputReader:
    """Class that read a mess input file and transforms it into
     an object with easily extractable data."""
    def __init__(self, settings: dict) -> None:
        """Save the file content as a string for further manipulation

        Args:
            settings (dict): Content of the input file
                             with additional default parameters
        """

        self.filename: str = settings["initial_mess"]
        self.SOP: SOP = SOP()  # Set of parameters
        self.SOP.rc_temp = settings["rc_temp"]
        self.SOP.rc_pres = settings["rc_pres"]
        self.SOP.ct_names = settings["ct_names"]

        if os.path.isfile(path=self.filename):
            with open(file=self.filename, mode='r') as f:
                self.file: list[str] = f.readlines()

        self.template: list[str] = []

    def read(self) -> tuple[SOP, list[str]]:
        """Reads a mess input file and transforms it into a
        SetOfParameter object and a mess_template file.

        Returns:
            list[SOP, list[str]]: [SetOfParameters, mess_template]
        """
        name = ''
        skip = 0
        for lnum, line in enumerate(self.file):

            # Avoid writing data in template
            if skip:
                skip -= 1
                continue

            # General parameters

            if line.lstrip().casefold().startswith('temperaturelist'):
                self.save_temperatures(lnum=lnum)
                self.template.append(line.split()[0] + " {SOP.r_rc_temp}\n")
                continue
            elif line.lstrip().casefold().startswith('pressurelist'):
                self.save_pressures(lnum=lnum)
                self.template.append(line.split()[0] + " {SOP.r_rc_pres}\n")
                continue
            elif line.lstrip().casefold().startswith('factor'):
                self.SOP.factor = float(line.split()[1])
                self.template.append(line.split()[0] + " {SOP.factor}\n")
                continue
            elif line.lstrip().casefold().startswith('power'):
                self.SOP.power = float(line.split()[1])
                self.template.append(line.split()[0] + " {SOP.power}\n")
                continue
            elif line.lstrip().casefold().startswith('epsilons'):
                self.template.append(line.split()[0] + "{SOP.r_epsilons}")
                for arg in line.split()[1:]:
                    self.SOP.epsilons.append(float(arg))
                continue
            elif line.lstrip().casefold().startswith('sigmas'):
                self.template.append(line.split()[0] + "{SOP.r_sigmas}")
                for arg in line.split()[1:]:
                    self.SOP.sigmas.append(float(arg))
                continue

            # Set the name of the current item

            # WELL
            elif line.lstrip().casefold().startswith('well '):
                last_item = 'well'
                name: str = line.split()[1]
                if name not in self.SOP.items:
                    self.SOP.add_new_well(name=name)
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{name}.name" \
                    + "}\n"
                self.template.append(new_line)
            # BIMOLECULAR
            elif line.lstrip().casefold().startswith('bimolecular '):
                last_item = 'bimo'
                name: str = line.split()[1]
                if name not in self.SOP.items:
                    self.SOP.add_new_bimol(name=name)
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{name}.name" \
                    + "}\n"
                self.template.append(new_line)
            # BARRIER
            elif line.lstrip().casefold().startswith('barrier '):
                last_item = 'barr'
                name, lside, rside = line.split()[1:4]
                if name not in self.SOP.items:
                    self.SOP.add_new_barrier(name=name,
                                             lside=lside,
                                             rside=rside)
                new_line: str = line.split()[0] + " {" + f"{name}.name" + "}"
                new_line += " {" + f"{lside}.name" + "}"
                new_line += " {" + f"{rside}.name" + "}\n"
                self.template.append(new_line)
            # Set barrierless to save symmetry factor
            elif line.lstrip().casefold().startswith('core phasespacetheory'):
                self.SOP.items[name].barrierless = True
                self.template.append(line)
            # FRAGMENT
            elif line.lstrip().casefold().startswith('fragment')\
                    and 'geom' not in line.casefold():
                last_item = 'frag'
                fname: str = line.split()[1]
                if not isinstance(self.SOP.items[name], Barrier):
                    if fname not in self.SOP.items[name].frag_names():
                        self.SOP.items[name].add_new_frag(fname)
                        if fname not in self.SOP.items:
                            self.SOP.items[fname] = \
                                self.SOP.items[name].fragments[-1]
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{fname}.name" \
                    + "}\n"
                self.template.append(new_line)

            # Add parameters to items

            # GEOMETRY
            elif line.lstrip().casefold().startswith('geometry')\
                    and 'rotor' not in self.file[lnum-1].casefold():
                natom = int(line.split()[1])
                self.template.append(line)
                if last_item == 'frag':
                    self.save_geom(fname, lnum, natom)
                else:
                    self.save_geom(name, lnum, natom)
            elif line.lstrip().casefold().startswith('fragmentgeometry'):
                natom = int(line.split()[1])
                self.template.append(line)
                self.save_geom(fname, lnum, natom)

            # FREQUENCIES
            elif line.lstrip().casefold().startswith('frequencies'):
                nfreq = int(line.split()[1])
                self.template.append(line)
                if last_item == 'frag':
                    nlines: int = self.save_freq(name=fname,
                                                 lnum=lnum,
                                                 nfreq=nfreq)
                else:
                    nlines: int = self.save_freq(name=name,
                                                 lnum=lnum,
                                                 nfreq=nfreq)
                skip += nlines

            # HINDERED ROTOR
            elif line.lstrip().casefold().startswith('rotor') and\
                    line.split()[1].casefold() == 'hindered':
                self.template.append(line)
                if last_item == 'frag':
                    skip += self.save_rotor(name=fname,
                                            lnum=lnum)
                else:
                    skip += self.save_rotor(name=name,
                                            lnum=lnum)

            # ENERGY
            elif line.lstrip().casefold().startswith('zeroenergy'):
                energy = float(line.split()[1])
                if last_item == 'frag':
                    self.save_energy(name=fname,
                                     energy=energy,
                                     lnum=lnum)
                else:
                    self.save_energy(name=name,
                                     energy=energy,
                                     lnum=lnum)
            elif line.lstrip().casefold().startswith('groundenergy'):
                # for bimolec
                energy = float(line.split()[1])
                self.save_energy(name=name,
                                 energy=energy,
                                 lnum=lnum)

            # TUNNELING
            elif line.lstrip().casefold().startswith('tunneling'):
                tun_type = str(line.split()[1])
                self.template.append(line)
                skip += self.save_tunneling(name=name,
                                            tun_type=tun_type,
                                            lnum=lnum)

            # SYMMETRY FACTOR
            elif line.lstrip().casefold().startswith('symmetryfactor') \
            and isinstance(self.SOP.items[name], Barrier) \
            and self.SOP.items[name].barrierless:
                sf = float(line.split()[1])
                self.save_symmetry_factor(name=name,
                                          symFact=sf,
                                          lnum=lnum)
            # All other lines
            else:
                self.template.append(line)

        return (self.SOP, self.template)

    def save_temperatures(self, lnum: int) -> None:
        """Save temperatures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """
        if self.SOP.rc_temp == []:
            args: list[str] = self.file[lnum].split()
            temp_list: list = []
            arg_n = 1
            # There should be no negative numbers in the list
            while arg_n < len(args) and\
                    args[arg_n].replace(".", "")\
                               .isnumeric():
                temp_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.rc_temp = temp_list

    def save_pressures(self, lnum: int) -> None:
        """Save pressures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """
        if self.SOP.rc_pres == []:
            args: list[str] = self.file[lnum].split()
            pres_list: list = []
            arg_n = 1
            # There should be no negative numbers in the list
            while arg_n < len(args) and\
                    args[arg_n].replace(".", "")\
                               .isnumeric():
                pres_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.rc_pres = pres_list

    def save_freq(self, name: str, lnum: int, nfreq: int) -> int:
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
        for lnum2, line in enumerate(self.file[lnum+1:]):
            args: list[str] = line.split()
            arg_n = 0
            while arg_n < len(args) and args[arg_n].replace(".",
                                                            "").isnumeric():

                freqs.append(float(args[arg_n]))
                arg_n += 1
            if len(freqs) == nfreq:
                self.SOP.set_freqs(name, freqs)
                new_line: str = " {" + f"{name}" + ".r_freq}\n"
                self.template.append(new_line)
                return lnum2+1
            if lnum2 > nfreq:
                raise TypeError("Error in Mess file: wrong number of freq")
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

        scan = []
        npot = 0
        skip = 0
        symmetry = 0
        # Read the file
        for lnum2, line in enumerate(self.file[lnum+1:]):
            # SCAN
            if line.lstrip().casefold().startswith('potential'):
                npot = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif npot != 0 and npot != len(scan):
                args: list[str] = line.split()
                arg_n = 0
                while arg_n < len(args) and args[arg_n].replace(".", "")\
                                                       .replace("-", "")\
                                                       .isnumeric():
                    scan.append(float(args[arg_n]))
                    arg_n += 1
                if lnum2 > npot:
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                skip += 1
                continue

            # Other keys
            elif line.lstrip().casefold().startswith('thermalpowermax'):
                thermalpowermax = float(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('group'):
                group: list[int] = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis: list[int] = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            # END
            elif line.lstrip().casefold().startswith('end'):
                rot_num: int = self.SOP.set_rotor(name,
                                                  thermalpowermax,
                                                  group,
                                                  axis,
                                                  symmetry,
                                                  scan)
                new_line: str = " {" \
                    + f"{name}" \
                    + ".r_scan" \
                    + f"({rot_num})" \
                    + "}\n"
                self.template.append(new_line)
                self.template.append(line)
                skip += 1
                return skip
            else:
                raise Error(f'Incorrect termination of rotor for {name}')
        return 0

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
        """
        symbols: str = ''
        geom: list = []
        for line in self.file[lnum+1:lnum+natom+1]:
            symbols += line.split()[0]
            x, y, z = line.split()[1:4]
            geom.append([float(x), float(y), float(z)])

        self.SOP.set_structure(name, symbols, geom)

    def save_energy(self,
                    name: str,
                    energy: float,
                    lnum: int) -> None:
        """Save the energy of the object 'name'
        in the SOP object.

        Args:
            name (str): Object's (well, bimol, barrier) name
            energy (float): Energy of the object in (kcal/mol)
            lnum (int): Line number in input file
        """
        self.SOP.items[name].energy = energy
        new_line: str = f"{self.file[lnum].split()[0]}" \
                        + " {" + f"{name}" \
                        + ".energy}\n"
        self.template.append(new_line)

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
        # well_depth: list[float] = [np.inf, np.inf]
        well_idx = 0
        skip = 0
        for line in self.file[lnum:]:
            if line.lstrip().casefold().startswith('imaginaryfrequency'):
                ifreq = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".ifreq}\n"
                self.SOP.items[name].ifreq = ifreq
                self.template.append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('cutoffenergy'):
                # coff = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".r_coff}\n"
                self.template.append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('welldepth'):
                # well_depth[well_idx] = float(line.split()[1])
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
                self.template.append(new_line)
                well_idx += 1
                skip += 1
            elif line.lstrip().casefold().startswith('end'):
                break
        # self.SOP.save_tunnelling(name, ifreq, coff, well_depth)
        return skip

    def save_symmetry_factor(self,
                             name: str,
                             symFact: float,
                             lnum: int) -> None:
        """Save the symmetry factor of the object 'name'
        in the SOP object.

        Args:
            name (str): Object's (well, bimol, barrier) name
            symFact (float): Symmetry factor of the object in (kcal/mol)
            lnum (int): Line number in input file
        """
        self.SOP.items[name].symFact = symFact
        new_line: str = f"{self.file[lnum].split()[0]}" \
                        + " {" + f"{name}" \
                        + ".symFact}\n"
        self.template.append(new_line)
