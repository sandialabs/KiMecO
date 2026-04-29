import numpy as np
from kimeco.parameters import SOP
import re
from kimeco.logger_config import KMOLogger


class MessOutputReader:
    """Class that read a mess output file and transforms it into
     a set of (T/P dependent) rate constants."""
    def __init__(self,
                 filename: str,
                 settings: dict,
                 sop: SOP,
                 klog: KMOLogger) -> None:

        self.klog: KMOLogger = klog
        with open(file=filename, mode='r') as f:
            self.file: list[str] = f.readlines()

        if settings['postprocess']:
            self.temp: list[float] = settings["pp_temp"]
            self.pres: list[float] = settings["pp_pres"]
        else:
            self.temp = settings["rc_temp"]
            self.pres = settings["rc_pres"]

        self.species: list[str] = sop.wells_names
        self.species.extend(sop.bimols_names)

        # T/P dependant rate constants
        self.rc: np.ndarray = np.full(shape=(len(self.pres),
                                      len(self.temp),
                                      len(self.species),
                                      len(self.species)),
                                      fill_value=0.0)

        # High-pressure rate constants
        self.hp_rc: np.ndarray = np.full(shape=(len(self.temp),
                                         len(self.species),
                                         len(self.species)),
                                         fill_value=0.0)

        self.lnum: int = 0
        # Map linking indexes to species name in first parsed table.
        self.tbl_map: dict[str, int] = {}

    @staticmethod
    def _safe_index(grid: list[float], value: float) -> int:
        """Return index in grid with tolerant float matching."""
        try:
            return grid.index(value)
        except ValueError:
            rounded_val = round(value, 5)
            rounded_grid = [round(v, 5) for v in grid]
            if rounded_val in rounded_grid:
                return rounded_grid.index(rounded_val)

            nearest_idx = min(
                range(len(grid)),
                key=lambda i: abs(grid[i] - value)
            )
            nearest_val = grid[nearest_idx]
            if rounded_val == 0.0:
                if abs(nearest_val) <= 1e-12:
                    return nearest_idx
            else:
                rel_err = abs(nearest_val - value) / abs(value)
                if rel_err <= 1e-4:
                    return nearest_idx
            raise

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
                    t_idx: int = self._safe_index(self.temp, temp)
                    pres = float(line.split()[6])
                    p_idx: int = self._safe_index(self.pres, pres)
                    continue
                elif line.lstrip().casefold().startswith('temperature'):
                    temp = float(line.split()[2])
                    t_idx: int = self._safe_index(self.temp, temp)
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
        if self.lnum == 0:
            save_map = True
            self.lnum = lnum
        else:
            save_map = False

        # Create the table
        table: np.ndarray = np.full(shape=(len(self.species),
                                    len(self.species)),
                                    fill_value=0.0)

        # Write the table
        for From, line in enumerate(self.file[lnum+1:]):
            if line == "\n":
                break
            rates: list[str] = line.split()[1:]
            if save_map:
                self.tbl_map[line.split()[0]] = From
            for To, value in enumerate(rates):
                if "*" in value:
                    continue
                else:
                    try:
                        table[From, To] = float(value)
                    except ValueError as e:
                        # Happens when no space between two columns
                        # no space when the right value is very small
                        # and start with a minus sign
                        self.klog.warning(str(e))
                        table[From, To] = float(
                            re.sub(r'-\d+.\d+e-\d\d\d',
                                   ' 0.0 ',
                                   value).strip().split()[0])
                        table[From, To+1] = 0.0

        # Save the table
        if p_idx == len(self.pres):
            self.hp_rc[t_idx] = table
        else:
            self.rc[p_idx, t_idx] = table
