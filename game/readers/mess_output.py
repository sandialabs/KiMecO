from typing import Any
import numpy as np
from game.parameters import SOP

class MessOutputReader:
    """Class that read a mess output file and transforms it into
     a set of (T/P dependent) rate constants."""
    def __init__(self, filename: str, settings: dict, sop: SOP):

        with open(file=filename, mode='r') as f:
            self.file: list[str] = f.readlines()

        self.temp: list = settings["rc_temp"]
        self.pres: list = settings["rc_pres"]

        self.species: list[str] = sop.wells_names()
        self.species.extend(sop.bimols_names())

        self.rc: Any = np.full(shape=(len(self.pres),
                                      len(self.temp),
                                      len(self.species),
                                      len(self.species)),
                               fill_value=0.0)

        self.hp_rc: Any = np.full(shape=(len(self.temp),
                                         len(self.species),
                                         len(self.species)),
                                  fill_value=0.0)

    def read(self) -> None:    
        recording = False

        for lnum, line in enumerate(self.file):

            # Tables section, start recording
            if line.lstrip().casefold().startswith('species-species rate'):
                recording = True
                continue

            if recording:

                # Set the pressure and temperature indexes
                if 'temperature' in line.casefold() and\
                    'pressure' in line.casefold():
                    temp = float(line.split()[2])
                    t_idx: int = self.temp.index(temp)
                    pres = float(line.split()[6])
                    p_idx: int = self.pres.index(pres)
                    continue
                elif line.lstrip().casefold().startswith('temperature'):
                    temp = float(line.split()[2])
                    t_idx: int = self.temp.index(temp)
                    p_idx: int = len(self.pres)
                elif "From\\To" in line:
                    self.save_table(lnum=lnum,
                                    t_idx=t_idx,
                                    p_idx=p_idx)
                elif "_______________" in line:
                    break

    def save_table(self,
                   lnum: int,
                   t_idx: int,
                   p_idx: int) -> None:
        """Save the rc of the table at line lnum

        Args:
            lnum (int): line_number
            t_idx (int): temperaturte index
            p_idx (int): pressure index
        """

        # Create the table
        table = np.full(shape=(len(self.species),
                               len(self.species)),
                        fill_value=0.0)

        # Write the table
        for From, line in enumerate(self.file[lnum+1:]):
            if line == "\n":
                break
            rates: list[str] = line.split()[1:]
            for To, value in enumerate(rates):
                if "*" in value:
                    continue
                    # table[From, To] = value
                else:
                    table[From, To] = float(value)

        # Save the table
        if p_idx == len(self.pres):
            self.hp_rc[t_idx] = table
        else:
            self.rc[t_idx, p_idx] = table
