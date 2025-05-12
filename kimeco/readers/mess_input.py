from curses.ascii import isdigit
from uu import Error

from kimeco.parameters import SOP
from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.rotors.internalrotation import InternalRotation
from kimeco.rotors.mrotor import MultiRotor

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
        self.SOP: SOP = SOP(score_species=settings['score_sp'])
        self.SOP.rc_temp = settings["rc_temp"]
        self.SOP.rc_pres = settings["rc_pres"]
        self.SOP.ct_names = settings["ct_names"]
        self.files2copy: list[str] = []

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
                self.template.append(line.split()[0] + " {SOP.r_epsilons}\n")
                for arg in line.split()[1:]:
                    if arg.replace('.', '').replace('-', '').isnumeric():  # Avoid reading comments
                        self.SOP.epsilons.append(float(arg))
                    else:
                        break
                continue
            elif line.lstrip().casefold().startswith('sigmas'):
                self.template.append(line.split()[0] + " {SOP.r_sigmas}\n")
                for arg in line.split()[1:]:
                    if arg.replace('.', '').replace('-', '').isnumeric():  # Avoid reading comments
                        self.SOP.sigmas.append(float(arg))
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
                    self.SOP.add_new_well(name=name)
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{name}.name" \
                    + "}\n"
                self.template.append(new_line)
                continue
            # BIMOLECULAR
            elif line.lstrip().casefold().startswith('bimolecular'):
                last_item = 'bimo'
                name: str = line.split()[1]
                if name not in self.SOP.items:
                    self.SOP.add_new_bimol(name=name)
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{name}.name" \
                    + "}\n"
                self.template.append(new_line)
                continue
            # BARRIER
            elif line.lstrip().casefold().startswith('barrier'):
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
                continue
            # Different types of barrierless
            elif (line.lstrip().casefold().startswith('core')
                  and line.lstrip().casefold().split()[1] == 'phasespacetheory'
                  and isinstance(self.SOP.items[name], Barrier)):
                self.SOP.items[name].barrierless = True
                self.template.append(line)
                skip += self.save_phasespacetheory(name, lnum)
                continue
            elif (line.lstrip().casefold().startswith('core')
                  and line.lstrip().casefold().split()[1] == 'rotd'
                  and isinstance(self.SOP.items[name], Barrier)):
                self.SOP.items[name].barrierless = True
                self.template.append(line)
                skip += self.save_rotd(name, lnum)
                continue
            # FRAGMENT
            elif line.lstrip().casefold().startswith('fragment')\
                    and 'geom' not in line.casefold():
                last_item = 'frag'
                fname: str = line.split()[1]
                if isinstance(self.SOP.items[name], Bimolecular):
                    if fname not in self.SOP.items[name].frag_names:
                        self.SOP.items[name].add_new_frag(fname)
                        if fname not in self.SOP.items:
                            self.SOP.items[fname] = \
                                self.SOP.items[name].fragments[-1]
                new_line: str = line.split()[0] \
                    + " {" \
                    + f"{fname}.name" \
                    + "}\n"
                self.template.append(new_line)
                continue

            # Dummy
            elif line.lstrip().casefold().startswith('dummy'):
                self.template.append(line)
                self.SOP.items[name].dummy = True
                continue

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
                continue
            elif line.lstrip().casefold().startswith('fragmentgeometry'):
                natom = int(line.split()[1])
                self.template.append(line)
                self.save_geom(fname, lnum, natom)
                continue

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
                continue

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
                continue
                    
            # MULTI ROTOR
            elif (line.lstrip().casefold().startswith('core') and
                  line.split()[1].casefold() == 'multirotor'):
                self.template.append(line)
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
                                     lnum=lnum)
                else:
                    self.save_energy(name=name,
                                     energy=energy,
                                     lnum=lnum)
                continue
            elif line.lstrip().casefold().startswith('groundenergy'):
                # for bimolec
                energy = float(line.split()[1])
                self.save_energy(name=name,
                                 energy=energy,
                                 lnum=lnum)
                continue

            # TUNNELING
            elif line.lstrip().casefold().startswith('tunneling'):
                tun_type = str(line.split()[1])
                self.template.append(line)
                skip += self.save_tunneling(name=name,
                                            tun_type=tun_type,
                                            lnum=lnum)
                continue

            # All other lines
            else:
                self.template.append(line)

        for bar in self.SOP.barriers:
            for well_idx in range(len(bar.connected)):
                if bar.connected[well_idx].dummy:
                    bar.connected[well_idx].energy = \
                        bar.energy - bar._well_depth[well_idx]
        self.SOP.files2copy = self.files2copy
        return (self.SOP, self.template)

    def save_phasespacetheory(self,
                              name: str,
                              lnum: int):
        """Save the barierless parameters in case of a phasespacetheory core

        Args:
            name (str): name of the barrier
            lnum (int): line number from wich to record this core

        Returns:
            int: number of line to skip to not double read this core
        """
        bar: Barrier = self.SOP.items[name]
        skip = 0
        # Read the file
        for lnum2, line in enumerate(self.file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                self.template.append(new_line)
            elif line.lstrip().casefold().startswith('potentialprefactor'):
                bar.pp = float(line.split()[1])
                skip += 1
                self.template.append(line)
            elif line.lstrip().casefold().startswith('potentialpowerexponent'):
                bar.ppe = float(line.split()[1])
                skip += 1
                self.template.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                self.template.append(line)

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
        # Read the file
        for lnum2, line in enumerate(self.file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                self.template.append(new_line)
            elif line.lstrip().casefold().startswith('file'):
                bar.file = line.split()[1]
                if bar.file not in self.files2copy:
                    self.files2copy.append(bar.file)
                skip += 1
                self.template.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                self.template.append(line)

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

        # default
        thermalpowermax = 0.0
        scan: list[float] = []
        fexp: list[float] = []
        fcoef: list[float] = []
        npot: int = 0
        skip: int = 0
        symmetry: int = 0
        local_skip: int = 0
        rot_num: int = len(self.SOP.items[name].h_rotors)
        # Read the file
        for lnum2, line in enumerate(self.file[lnum+1:]):
            # SCAN
            if local_skip:
                local_skip -= 1
                self.template.append(line)
                continue

            if line.lstrip().casefold().startswith('potential'):
                npot = int(line.split()[1])
                self.template.append(line)
                new_line: str = " {" \
                    + f"{name}" \
                    + ".r_scan" \
                    + f"({rot_num})" \
                    + "}\n"
                self.template.append(new_line)
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
                self.template.append(line)
                nexp = int(line.split()[1])
                fexp = [
                    exp_line.split()[0]
                    for exp_line in self.file[lnum2+1:lnum2+nexp]]
                fcoef = [
                    exp_line.split()[1]
                    for exp_line in self.file[lnum2+1:lnum2+nexp]]
                for li in self.file[lnum2+1:lnum2+nexp]:
                    self.template.append(li)
                skip += 1 + nexp
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
            elif line.lstrip().casefold().startswith('geometry'):
                local_skip += int(line.split()[1])
                skip += int(line.split()[1]) + 1
                self.template.append(line)
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.template.append(line)
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
                self.template.append(line)
                skip += 1
                return skip
            elif (line.lstrip().startswith('#') or
                  line.lstrip().startswith('!') or
                  line.lstrip().startswith('') or
                  line.lstrip().startswith('+++')):
                self.template.append(line)
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

        for lnum2, line in enumerate(self.file[lnum+1:]):
            # Skip through the lines of internal rotation
            if ir_skip != 0:
                ir_skip -= 1
                continue
            # SymmetryFactor
            if line.lstrip().casefold().startswith('symmetryfactor'):
                sf = float(line.split()[1])
                new_line: str = f"{self.file[lnum+lnum2+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".symFact}\n"
                self.template.append(new_line)
                skip += 1
                continue

            # InterpolationEnergyMax
            elif line.lstrip().casefold().startswith('interpolationenergymax'):
                iem = float(line.split()[1])
                new_line: str = f"{self.file[lnum+lnum2+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".iem}\n"
                self.template.append(new_line)
                skip += 1
                continue

            # PotentialEnergySurface
            elif line.lstrip().casefold().startswith('potentialenergysurface'):
                pes = line.split()[1]
                if pes not in self.files2copy:
                    self.files2copy.append(pes)
                new_line: str = f"{self.file[lnum+lnum2+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".file}\n"
                self.template.append(new_line)
                skip += 1
                continue

            # QuantumLevelEnergyMax
            elif line.lstrip().casefold().startswith('quantumlevelenergymax'):
                qlem = float(line.split()[1])
                new_line: str = f"{self.file[lnum+lnum2+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".qlem}\n"
                self.template.append(new_line)
                skip += 1
                continue

            # InternalRotation
            elif line.lstrip().casefold().startswith('internalrotation'):
                self.template.append(line)
                skip += 1
                ir_skip, ir = self.create_internal_rotation(
                    name=name,
                    lnum=lnum2+lnum+1)
                irs.append(ir)
                skip += ir_skip
                continue
            # END
            elif line.lstrip().casefold().startswith('end'):
                self.SOP.items[name].m_rotors.append(
                    MultiRotor(
                        symmetryFactor=sf,
                        interpolationEnergyMax=iem,
                        potentialEnergySurface=pes,
                        quantumLevelEnergyMax=qlem,
                        internal_rot=irs
                    )
                )
                self.template.append(line)
                skip += 1
                return skip
            elif (line.lstrip().casefold().startswith('#') or
                  line.lstrip().casefold().startswith('!') or
                  line.lstrip().casefold().startswith('') or
                  line.lstrip().casefold().startswith('+++')):
                self.template.append(line)
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
        for lnum2, line in enumerate(self.file[lnum+1:]):
            if line.lstrip().casefold().startswith('group'):
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
            elif line.lstrip().casefold().startswith('massexpansionsize'):
                mes = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('potentialexpansionsize'):
                pes = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemin'):
                hamiltonsizemin = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemax'):
                hamiltonsizemax = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('gridsize'):
                gridsize = int(line.split()[1])
                self.template.append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('end'):
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
                self.template.append(line)
                skip += 1
                return (skip, ir)
            elif (line.lstrip().startswith('#') or
                  line.lstrip().startswith('!') or
                  line.lstrip().startswith('') or
                  line.lstrip().startswith('+++')):
                self.template.append(line)
                skip += 1
                continue
            else:
                raise AttributeError('Unknown keyword for InternalRotation')

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
        if isinstance(self.SOP.items[name], Barrier):
            self.SOP.items[name]._energy = energy
        else:
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
        well_depth: list[float] = [-1.0, -1.0]
        bar: Barrier = self.SOP.items[name]
        well_idx = 0
        skip = 0
        for line in self.file[lnum+1:]:
            if line.lstrip().casefold().startswith('imaginaryfrequency'):
                ifreq = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".ifreq}\n"
                bar.ifreq = ifreq
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
                self.template.append(new_line)
                well_idx += 1
                skip += 1
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                self.template.append(line)
                skip += 1
