import cantera as ct
import numpy as np


class MessData(ct.ExtensibleRateData):
    __slots__ = ("T", "P")

    def __init__(self) -> None:
        self.T = 0.0
        self.P = 0.0

    def update(self, gas) -> bool:
        update = False
        T: float = gas.T
        P: float = gas.P
        if self.T != T:
            self.T: float = T
            update = True
        if self.P != P:
            self.P: float = P
            update = True

        return update


@ct.extension(name="Mess-data", data=MessData)
class MessRate(ct.ExtensibleRate):
    __slots__ = ("rc", "Pgrid", "Tgrid")

    def set_parameters(self, params, units) -> None:
        self.rc: np.ndarray = np.array(params.convert("rc", 'cm^3/s/molec'))
        self.Pgrid: np.ndarray = np.array(params.convert("Pgrid", 'Pa'))
        self.Tgrid: np.ndarray = np.array(params.convert("Tgrid", 'K'))

    def get_parameters(self, params) -> None:
        params["rc"] = params.set_quantity("rc", self.rc, 'cm^3/s/molec')
        params["Pgrid"] = params.set_quantity("Pgrid", self.Pgrid, 'Pa')
        params["Tgrid"] = params.set_quantity("Tgrid", self.Tgrid, 'K')

    def validate(self, equation, soln) -> None:
        # if soln.P not in self.Pgrid:
        #     raise ValueError(f"Pressure of simulation {soln.P} not found in Pgrid")
        # if soln.T not in self.Tgrid:
        #     raise ValueError(f"Temperature of simulation not found Tgrid")
        # pindex = np.where(self.Pgrid == soln.P)[0][0]
        # tindex = np.where(self.Tgrid == soln.T)[0][0]
        # if self.rc[pindex, tindex] < 0:
        #     raise ValueError(f"Found negative reaction coefficient for \
        #                      reaction {equation}")
        pass

    def eval(self, data) -> float:
        Pindex: int = np.where(self.Pgrid == data.P)[0][0]
        Tindex: int = np.where(self.Tgrid == data.T)[0][0]
        return self.rc[Pindex, Tindex]
