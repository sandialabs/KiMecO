import cantera as ct
import cantera.with_units as ctu
from typing import Any
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity
ureg.formatter.default_format = '.5f'
ct_any: Any = ct


class MessData(ct_any.ExtensibleRateData):
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


@ct_any.extension(name="Mess-data", data=MessData)
class MessRate(ct_any.ExtensibleRate):
    __slots__ = ("rc",
                 "Pgrid",
                 "Tgrid",
                 "units")

    def set_parameters(self,
                       params,
                       units) -> None:

        for idx, p in enumerate(params['Pgrid']):
            if isinstance(p, str) :  # and 'torr' in p
                params['Pgrid'][idx] = f'{Q_(p).to("Pa").magnitude} Pa'

        self.Pgrid = params.convert("Pgrid", 'Pa')
        self.Tgrid = params.convert("Tgrid", 'K')
        self.rc = []
        for pidx in range(len(self.Pgrid)):
            self.rc.append([])
            for tidx in range(len(self.Tgrid)):
                self.rc[-1].append(
                    params.convert_rate_coeff(f"rc_{pidx}_{tidx}",
                                              units))

    def get_parameters(self, params) -> None:
        params.set_quantity("Pgrid", self.Pgrid, 'Pa')
        params.set_quantity("Tgrid", self.Tgrid, 'K')
        for pidx in range(len(self.Pgrid)):
            for tidx in range(len(self.Tgrid)):
                params.set_quantity(f"rc_{pidx}_{tidx}",
                                    self.rc[pidx][tidx],
                                    self.conversion_units)
        for idx, p in enumerate(self.Pgrid):
            self.Pgrid[idx] = round(p, 5)
        for idx, t in enumerate(self.Tgrid):
            self.Tgrid[idx] = round(t, 5)

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

    @staticmethod
    def _grid_index(grid: list[float], value: float) -> int:
        """Return index of value in grid with a bounded nearest fallback.

        Cantera may provide state values that differ slightly from the
        user-provided grid because of unit conversion and floating-point
        representation.
        """
        if not grid:
            raise ValueError("Empty grid provided for custom rate lookup")

        rounded_value = round(value, 5)
        try:
            return grid.index(rounded_value)
        except ValueError:
            nearest_idx = min(
                range(len(grid)), key=lambda i: abs(grid[i] - rounded_value)
            )
            nearest_value = grid[nearest_idx]

            # Only accept nearest point if it is within 0.01%.
            if rounded_value == 0.0:
                if abs(nearest_value) <= 1e-12:
                    return nearest_idx
            else:
                rel_err = (
                    abs(nearest_value - rounded_value) /
                    abs(rounded_value)
                )
                if rel_err <= 1e-4:
                    return nearest_idx

            raise

    def eval(self, data) -> float:
        for idx, p in enumerate(self.Pgrid):
            self.Pgrid[idx] = round(p, 5)
        for idx, t in enumerate(self.Tgrid):
            self.Tgrid[idx] = round(t, 5)
        Pindex: int = self._grid_index(self.Pgrid, data.P)
        Tindex: int = self._grid_index(self.Tgrid, data.T)
        return self.rc[Pindex][Tindex]
