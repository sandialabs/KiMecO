import cantera as ct
import cantera.with_units as ctu
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity
ureg.default_format = '.5f'


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
    __slots__ = ("rc",
                 "Pgrid",
                 "Tgrid",
                 "units")

    def set_parameters(self,
                       params,
                       units) -> None:

        for idx, p in enumerate(params['Pgrid']):
            if isinstance(p, str) and 'torr' in p:
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
        Pindex: int = self.Pgrid.index(round(data.P, 5))
        Tindex: int = self.Tgrid.index(round(data.T, 5))
        return self.rc[Pindex][Tindex]
