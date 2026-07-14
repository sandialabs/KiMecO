import os
import csv
import string
from typing import Any
import numpy as np
from numpy.typing import NDArray
from kimeco.experiments.experiment import Experiment
from kimeco.logger_config import KMOLogger
from kimeco.templates.sim_arr_tpl import ctjobtpl


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
                 new_tpl: bool,
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
        if data is None:
            _, self.data = self.read_data(data_file)
        else:
            self.data = data
        if error is None:
            _, self.error = self.read_data(error_file)
        else:
            self.error = error

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
