from curses.ascii import isdigit
from uu import Error

import numpy as np
from game.parameters import SOP
from game.barrier import Barrier

import os

class MessReader:
    """Class that read a mess file and transform it into
     an object with easily extractable data."""
    def __init__(self, filename: str) -> None:
        """Save the file content as a string for further manipulation"""
        #filename str: the filename of the mess file
        #structures: list of dict of structures encountered in the Mess file


        self.filename: str = filename  
        self.SOP = SOP() # Set of parameters

        if os.path.isfile(filename):
            with open(filename, 'r') as f:
                self.file: list[str] = f.readlines()
        self.template: list = []

    def read(self) -> list[SOP, list[str]]:
        name = ''
        skip = 0
        for lnum, line in enumerate(self.file):

            #Avoid writing data in template
            if skip:
                skip -= 1
                continue
            
            #General parameters

            if line.lstrip().casefold().startswith('factor'):
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


            #
            #Set the name of the current item
            #

            #WELL
            elif line.lstrip().casefold().startswith('well '):
                last_item = 'well'
                name: str = line.split()[1]
                if name not in self.SOP.items:
                    self.SOP.add_new_well(name)
                new_line: str = line.split()[0] + " {" + f"{name}.r_name" + "}\n"
                self.template.append(new_line)
            #BIMOLECULAR
            elif line.lstrip().casefold().startswith('bimolecular '):
                last_item = 'bimo'
                name: str = line.split()[1]
                if name not in self.SOP.items:
                    self.SOP.add_new_bimol(name)
                new_line: str = line.split()[0] + " {" + f"{name}.r_name" + "}\n"
                self.template.append(new_line)
            #BARRIER
            elif line.lstrip().casefold().startswith('barrier '):
                last_item = 'barr'
                name, lside, rside = line.split()[1:4]
                if name not in self.SOP.items:
                    self.SOP.add_new_barrier(name, lside, rside)
                new_line: str = line.split()[0] + " {" + f"{name}.r_name" + "}"
                new_line += " {" + f"{lside}.r_name" + "}"
                new_line += " {" + f"{rside}.r_name" + "}\n"
                self.template.append(new_line)
            #FRAGMENT
            elif line.lstrip().casefold().startswith('fragment')\
                and not 'geom' in line.casefold():
                last_item = 'frag'
                fname: str = line.split()[1]
                if not isinstance(self.SOP.items[name], Barrier):
                    if fname not in self.SOP.items[name].frag_names():
                        self.SOP.items[name].add_new_frag(fname)
                        if fname not in self.SOP.items:
                            self.SOP.items[fname] = self.SOP.items[name].fragments[-1]
                new_line: str = line.split()[0] + " {" + f"{fname}.r_name" + "}\n"
                self.template.append(new_line)

            #
            #Add parameters to items
            #
                    
            #GEOMETRY
            elif line.lstrip().casefold().startswith('geometry')\
                and 'rotor' not in self.file[lnum-1].casefold():
                natom = int(line.split()[1])
                self.template.append(line)
                if last_item == 'frag':
                    self.save_geom(fname, lnum, natom)
                else:
                    self.save_geom(name, lnum, natom)
                # skip += natom
            elif line.lstrip().casefold().startswith('fragmentgeometry'):
                natom = int(line.split()[1])
                self.template.append(line)
                self.save_geom(fname, lnum, natom)
                skip += natom
            
            #FREQUENCIES
            elif line.lstrip().casefold().startswith('frequencies'):
                nfreq = int(line.split()[1])
                self.template.append(line)
                if last_item == 'frag':
                    nlines: int = self.save_freq(fname, lnum, nfreq)
                else:
                    nlines: int = self.save_freq(name, lnum, nfreq)
                skip += nlines

            #HINDERED ROTOR
            elif line.lstrip().casefold().startswith('rotor') and\
               line.split()[1].casefold() == 'hindered':
                self.template.append(line)
                if last_item == 'frag':
                    skip += self.save_rotor(fname, lnum)
                else:
                    skip += self.save_rotor(name, lnum)
            
            #ENERGY
            elif line.lstrip().casefold().startswith('zeroenergy'):
                energy = float(line.split()[1])
                if last_item == 'frag':
                    self.save_energy(fname, energy, lnum)
                else:
                    self.save_energy(name, energy, lnum)


            #TUNNELING
            elif line.lstrip().casefold().startswith('tunneling'):
                tun_type = str(line.split()[1])
                self.template.append(line)
                skip += self.save_tunneling(name, tun_type, lnum)
            
            else:
                self.template.append(line)

        return [self.SOP, self.template]
            

    def save_freq(self, name: str, lnum: int, nfreq: int) -> int:
        """Save the next frequencies encountered in Mess in 
        the item name."""
        freqs: list = []
        for lnum2, line in enumerate(self.file[lnum+1:]):
            args: list[str] = line.split()
            arg_n = 0
            while arg_n < len(args) and\
                  args[arg_n].replace(".", "").isnumeric():
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
                   lnum: int) -> None:
        """Save the next hindered rotor encountered in Mess in 
        the last structure dictionary."""
        scan = []
        npot = 0
        skip = 0
        #Read the file
        for lnum2, line in enumerate(self.file[lnum+1:]):
            #SCAN
            if line.lstrip().casefold().startswith('potential'):
                npot = int(line.split()[1])
                self.template.append(line)
                skip +=1
                continue
            elif npot != 0 and npot != len(scan):
                args: list[str] = line.split()
                arg_n = 0
                while arg_n < len(args) and\
                      args[arg_n].replace(".", "").isnumeric():
                    scan.append(float(args[arg_n]))
                    arg_n += 1
                if lnum2 > npot:
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                skip +=1
                continue
                
            #Other keys
            elif line.lstrip().casefold().startswith('thermalpowermax'):
                thermalpowermax = float(line.split()[1])
                self.template.append(line)
                skip +=1
                continue
            elif line.lstrip().casefold().startswith('group'):
                group: list[int] = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.template.append(line)
                skip +=1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis: list[int] = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.template.append(line)
                skip +=1
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = float(line.split()[1])
                self.template.append(line)
                skip +=1
                continue
            #END
            elif line.lstrip().casefold().startswith('end'):
                rot_num: int = self.SOP.set_rotor(name,
                                   thermalpowermax,
                                   group,
                                   axis,
                                   symmetry,
                                   scan)
                new_line: str = " {" + f"{name}" + ".r_scan" + f"({rot_num})" + "}\n"
                self.template.append(new_line)
                self.template.append(line)
                skip +=1
                return skip
            else:
                print(line)
                raise Error(f'Incorrect termination of rotor for {name}')

    def save_geom(self,
                  name: str,
                  lnum: int,
                  natom: int) -> None:
        
        symbols: str = ''
        geom: list = []
        for line in self.file[lnum+1:lnum+natom]:
            symbols += line.split()[0]
            x, y, z = line.split()[1:4]
            geom.append([float(x), float(y), float(z)])

        self.SOP.set_structure(name, symbols, geom)
        # new_line: str = " {" + f"{name}" + ".r_struct}\n"
        # self.template.append(new_line)

    def save_energy(self,
                    name: str,
                    energy: float,
                    lnum: int) -> None:
        self.SOP.set_energy(name, energy)
        new_line: str = f"{self.file[lnum].split()[0]}" + " {" + f"{name}" + ".r_energy}\n"
        self.template.append(new_line)

    def save_tunneling(self,
                       name: str,
                       tun_type: str,
                       lnum: int) -> None:
        """Save the imaginary freq for tunneling and check left/right energies."""
        well_depth: list[float] = [np.inf, np.inf]
        well_idx = 0
        skip = 0
        for line in self.file[lnum:]:
            if line.lstrip().casefold().startswith('imaginaryfrequency'):
                ifreq = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" + " {" + f"{name}" + ".r_ifreq}\n"
                self.SOP.items[name].set_ifreq(ifreq)
                self.template.append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('cutoffenergy'):
                coff = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" + " {" + f"{name}" + ".r_coff}\n"
                self.template.append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('welldepth'):
                well_depth[well_idx] = float(line.split()[1])
                if well_idx == 0:
                    new_line: str = f"{line.split()[0]}" + " {" + f"{name}" + ".r_lenergy}\n"
                elif well_idx == 1:
                    new_line: str = f"{line.split()[0]}" + " {" + f"{name}" + ".r_renergy}\n"
                self.template.append(new_line)
                well_idx += 1
                skip += 1
            elif line.lstrip().casefold().startswith('end'):
                break
        self.SOP.save_tunnelling(name, ifreq, coff, well_depth)
        return skip
