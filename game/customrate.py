import cantera as ct
import numpy as np


class MessData(ct.ExtensibleRateData):
    __slots__ = ("T", "P")

    def __init__(self) -> None:
        self.T = None
        self.P = None

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
        self.rc: np.ndarray = params.convert("rc", units)
        self.Pgrid: np.ndarray = params.convert("Pgrid", units)
        self.Tgrid: np.ndarray = params.convert("Tgrid", units)

    def get_parameters(self, params) -> None:
        params["rc"] = params.set_quantity("rc", self.rc, params.units)
        params["Pgrid"] = params.set_quantity("Pgrid", self.Pgrid, params.units)
        params["Tgrid"] = params.set_quantity("Tgrid", self.Tgrid, params.units)

    def validate(self, equation, soln) -> None:
        if self.rc[self.P, self.T] < 0:
            raise ValueError(f"Found negative reaction coefficient for \
                             reaction {equation}")
        if soln.P not in self.Pgrid:
            raise ValueError(f"Pressure of simulation not found on \
                             rate coefficient grid")
        if soln.T not in self.Tgrid:
            raise ValueError(f"Temperature of simulation not found on \
                             rate coefficient grid")

    def eval(self, data) -> float:
        Pindex: int = np.where(self.Pgrid == data.P)[0][0]
        Tindex: int = np.where(self.Tgrid == data.T)[0][0]
        return self.rc[Pindex, Tindex]
