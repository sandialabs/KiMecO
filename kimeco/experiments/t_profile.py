import io
from copy import deepcopy
import os
import csv
import string
from typing import Any
import numpy as np
from numpy.typing import NDArray
import pyarrow.feather as feather
from kimeco.experiments.experiment import Experiment
from kimeco.logger_config import KMOLogger
from scipy.constants import gas_constant
from kimeco.templates.sim_arr_tpl import ctjobtpl
import cantera.with_units as ctu
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity


class TimeProfile(Experiment):
    EXP_TYPE: str = 'Time profile'
    REQUIRED_TPL_KEYS: frozenset[str] = frozenset(
        field_name
        for _, field_name, _, _ in string.Formatter().parse(ctjobtpl)
        if field_name is not None
    )

    def __init__(self,
                 temp: float,
                 pres: float,
                 composition: dict[str, float],
                 data_file: str,
                 error_file: str,
                 sim_file: str,
                 settings: dict[str, Any],
                 klog: KMOLogger,
                 species: list[str],
                 data: NDArray,
                 error: NDArray,
                 new_tpl: bool = True,
                 tpl_idx: int = 0,
                 weight: float = 1.0) -> None:
        super().__init__(
            temp,
            pres,
            composition,
            sim_file,
            settings,
            klog,
            species,
            new_tpl,
            tpl_idx,
            weight)
        # Weight of the different species in the score calculation
        self.sp_weights: NDArray | None = None
        self.data_file: str = data_file
        self.error_file: str = error_file
        self.data: NDArray = data
        self.error: NDArray = error

    @classmethod
    def from_db(cls,
                settings: dict[str, Any],
                db_row: tuple[int, int, Any]) -> 'TimeProfile':
        exp_id = db_row[1]
        exp: 'TimeProfile' = deepcopy(settings['experiments'][exp_id])
        new_buf = io.BytesIO(db_row[2])
        db_data = feather.read_feather(new_buf).to_numpy()
        exp.data = db_data.T
        del exp.error
        return exp


    @staticmethod
    def read_data(file: str) -> tuple[list[str], NDArray]:
        """Read the data file for this experiment

        Args:
            file (str): path to file
        Raises:
            FileNotFoundError: if the file does not exist
            ValueError: if the file is empty or has no header
            KeyError: if the first column is not 'time'
            TypeError: if any value cannot be converted to float
            ValueError: if there are no data rows

        Returns:
            tuple[list[str], NDArray]:
                headers and row-oriented matrix where row 0 is time and
                rows 1..N are species.
        """
        if not os.path.isfile(file):
            msg: str = f'Could not find file {file}'
            raise FileNotFoundError(msg)
        rows: list[list[float]] = []
        with open(file, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            if headers is None or len(headers) == 0:
                raise ValueError(f"Empty CSV header in {file}")
            if headers[0] != 'time':
                raise KeyError(
                    f"The first column should be 'time' in file {file}."
                )
            for ln, line in enumerate(reader):
                row: list[float] = []
                for header in headers:
                    try:
                        row.append(float(line[header]))
                    except (TypeError, ValueError) as e:
                        msg = 'Incorrect value detected' + \
                            f' line{ln} in file {file}' + \
                            f' column {header}' + '\n' + str(e)
                        raise TypeError(msg)
                rows.append(row)
        if len(rows) == 0:
            raise ValueError(f'No data rows in file {file}')
        matrix: NDArray = np.array(rows, dtype=float).T
        return headers, matrix

    @staticmethod
    def validate_pair(data_headers: list[str],
                      data: NDArray,
                      error_headers: list[str],
                      error: NDArray,
                      data_file: str,
                      error_file: str) -> None:
        """Validate the data and error arrays for this experiment.

        Args:
            data_headers (list[str]): Headers of the data array
            data (NDArray): Data array
            error_headers (list[str]): Headers of the error array
            error (NDArray): Error array
            data_file (str): Path to the data file
            error_file (str): Path to the error file

        Raises:
            ValueError: If headers do not match
            ValueError: If shapes do not match
            ValueError: If time grids do not match
        """
        if data_headers != error_headers:
            msg = f'Headers mismatch between {data_file} and {error_file}.'
            raise ValueError(msg)
        if data.shape != error.shape:
            msg = (
                f'Data/error shape mismatch for {data_file} '
                f'and {error_file}.'
            )
            raise ValueError(msg)
        if not np.array_equal(data[0], error[0]):
            msg = f'Time grid mismatch between {data_file} and {error_file}.'
            raise ValueError(msg)

    @property
    def legend(self) -> list[str]:
        """Get the legend for the plot

        Returns:
            list[str]: Legend for the plot
        """
        if hasattr(self, '_legend'):
            return self._legend
        else:
            return self.species

    def _set_legend(self,
                    legend: list[str] | None) -> None:
        """Set the legend for the plot

        Args:
            legend (list[str] | None): Legend for the plot
        """
        if legend is not None:
            if len(legend) != len(self.species):
                raise ValueError(
                    f"Legend length {len(legend)} does not match "
                    f"number of species {len(self.species)}"
                )
            self._legend = legend
        else:
            self._legend = self.species

    def _set_ylabel(self,
                    ax: Any,
                    y_unit: str) -> None:
        """Set the y-axis label for the plot

        Args:
            ax (Any): Matplotlib axis
            y_unit (str): Unit for the y-axis
        """
        if y_unit.lower() == 'ratio':
            ax.set_ylabel('Ratio')
        elif y_unit.lower() in ['mol fraction', 'mole fraction']:
            ax.set_ylabel('Mole Fraction')
        elif y_unit.lower() == 'density':
            ax.set_ylabel(r'Density (molecules/cm^3)')
        else:
            ax.set_ylabel(f'{y_unit.capitalize()} ({y_unit})')

    def convert_time(self,
                     time: NDArray,
                     x_unit: str) -> NDArray:
        """Convert time to the desired x_unit.

        Args:
            time (NDArray): Time array in seconds
            x_unit (str): Desired time unit

        Returns:
            NDArray: Time array converted to the desired x_unit
        """
        if x_unit.lower() == 'ms':
            return time * 1e3
        else:
            return Q_(time, 's').to(x_unit).magnitude

    def plot(self,
             ax: Any,
             y_unit='density',
             x_unit='ms',
             add_legend: bool = True,
             colors: list[str] | None = None,
             legend: list[str] | None = None) -> None:
        """Plot the experimental data

        Args:
            y_unit (str): Unit for the y-axis
            x_unit (str): Unit for the x-axis
            colors (list[str] | None): Colors for the plot
            add_legend (bool): Whether to display the legend
            legend (list[str] | None): Legend for the plot
        Raises:
            TypeError: if y_unit or x_unit is not a string
            ValueError: if y_unit or x_unit are not recongnized units
        """
        allowed_y_units = [
            'ratio',
            'mol fraction',
            'mole fraction',
            'density']
        if not isinstance(y_unit, str):
            raise TypeError(f"y_unit must be a string, got {type(y_unit)}")
        if y_unit.lower() not in allowed_y_units:
            raise ValueError(
                f"y_unit must be one of {allowed_y_units}, got {y_unit}"
            )
        allowed_x_units = ['ms'] + list(ureg.get_compatible_units('[time]'))
        if not isinstance(x_unit, str):
            raise TypeError(f"x_unit must be a string, got {type(x_unit)}")
        if x_unit.lower() not in allowed_x_units:
            raise ValueError(
                f"x_unit must be one of {allowed_x_units}, got {x_unit}"
            )
        if colors is not None and len(colors) != len(self.species):
            raise ValueError(
                f"Length of colors {len(colors)} does not match "
                f"number of species: {len(self.species)}"
            )
        try:
            import matplotlib.pyplot as plt
        except ImportError as e:
            raise ImportError(
                "matplotlib is required for plotting. "
                "Please install it using 'pip install matplotlib'."
            ) from e
        self._set_legend(legend)

        if y_unit.lower() != 'density':
            y_data = self._density2y_unit(
                self.data[1:],
                self.T,
                self.P,
                y_unit)
            if hasattr(self, 'error') and self.error is not None:
                y_error = self._density2y_unit(
                    self.error[1:],
                    self.T,
                    self.P,
                    y_unit)
        else:
            y_data = self.data[1:]
            if hasattr(self, 'error') and self.error is not None:
                y_error = self.error[1:]

        for i, label in enumerate(self.legend):
            if not add_legend:
                label = None
            ax.plot(
                self.convert_time(self.data[0], x_unit),
                y_data[i],
                label=label,
                color=colors[i] if colors is not None else None
            )
            if hasattr(self, 'error') and self.error is not None:
                ax.errorbar(
                    self.convert_time(self.data[0], x_unit),
                    y_data[i],
                    yerr=y_error[i],
                    fmt='o',
                    capsize=3
                )
        ax.set_xlabel(f'Time ({x_unit})')
        # ax.set_ylabel(f'{y_unit.capitalize()} ({y_unit})')
        ax.set_title(f'Time profile of {", ".join(self.species)} at {self.T} K and {self.P} Pa')
        if add_legend:
            ax.legend()

    @staticmethod
    def _density2y_unit(density: NDArray,
                        T: float,
                        P: float,
                        y_unit: str) -> NDArray:
        """Convert mole fractions to the desired y_unit.

        Args:
            density (NDArray): Densities (molecules/cm^3)
            T (float): Temperature in K
            P (float): Pressure in Pa
            y_unit (str): Desired y-axis unit

        Returns:
            NDArray: Converted values in the desired y_unit
        """
        if y_unit.lower() == 'ratio':
            return TimeProfile.density_to_ratio(
                density, T, P)
        elif y_unit.lower() in ['mol fraction', 'mole fraction']:
            return TimeProfile.density_to_ratio(
                density, T, P)
        elif y_unit.lower() == 'density':
            return density
        else:
            raise ValueError(f"Unsupported y_unit: {y_unit}")

    @staticmethod
    def density_to_ratio(density: NDArray,
                         T: float,
                         P: float) -> NDArray:
        """Convert densities to ratios using Cantera.

        Args:
            density (NDArray): Densities (molecules/cm^3)
            T (float): Temperature in K
            P (float): Pressure in Pa

        Returns:
            NDArray: Ratios (dimensionless)
        """
        R = Q_(gas_constant, 'J mol^-1 K^-1')
        Vol = Q_(1, 'cm^3')
        pres = Q_(P, 'Pa')
        temp = Q_(T, 'K')
        ntot = (pres*Vol/(R*temp)).to('molecule')

        return (density / ntot.magnitude)
