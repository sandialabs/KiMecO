import os
import csv
from typing import Any
from kimeco.experiments.experiment import Experiment
from kimeco.scoring_f.scoring import Scoring


class TimeProfile(Experiment):
    def __init__(self,
                 temp: float,
                 pres: float,
                 composition: dict[str, float],
                 data_file: str,
                 error_file: str,
                 scoring: Scoring,
                 sim_file: str,
                 settings: dict[str, Any]) -> None:
        super().__init__(
            temp,
            pres,
            composition,
            scoring,
            sim_file,
            settings)
        self.data_file: str = data_file
        self.error_file: str = error_file
        self._data: dict[str, dict[str, list[float]]] = {
            'prof': {},
            'err': {},
            }
        self.time: list[float] = []
        self.prof = self.read_data(data_file)
        self.err = self.read_data(data_file, error=True)

    @property
    def prof(self) -> dict[str, list[float]]:
        return self._data['prof']

    @property
    def err(self) -> dict[str, list[float]]:
        return self._data['err']

    def read_data(self,
                  file: str,
                  error: bool = False) -> None:
        """Read the data file for this experiment

        Args:
            file (str): path to file
            error (bool, optional): is error file. Defaults to False.

        Raises:
            FileNotFoundError: _description_
            KeyError: _description_
            TypeError: _description_
            TypeError: _description_
        """
        if not os.path.isfile(file):
            msg: str = f'Could not find file {file}'
            raise FileNotFoundError(msg)
        with open(file, mode='r', encoding='utf-8-sig') as f:
            csv_DictReader = csv.DictReader(f)
            ln = 0
            for line in csv_DictReader:
                if 'time' not in line:
                    msg = "A column should be the 'time'"
                    msg += f" in file {file}."
                    raise KeyError(msg)
                    # cancel_run = True
                else:
                    for header in line:
                        if header == 'time':
                            try:
                                self.time.append(
                                        float(line[header]))
                            except TypeError as e:
                                msg = 'Incorrect value detected' +\
                                    f' line{ln} in file {file}' +\
                                    f' column {header}' + '\n' + e
                                raise TypeError(msg)
                        elif header not in self.prof:
                            self._data['prof'][header] = []
                            self._data['err'][header] = []
                        try:
                            if error:
                                self._data['err'][header].append(
                                    float(line[header]))
                            else:
                                self._data['prof'][header].append(
                                    float(line[header]))
                        except TypeError as e:
                            msg = 'Incorrect value detected' +\
                                    f' line{ln} in file {file}' +\
                                    f' column {header}' + '\n' + e
                            raise TypeError(msg)
                            # cancel_run = True
                ln += 1
