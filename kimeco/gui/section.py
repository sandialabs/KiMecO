from abc import ABC, abstractmethod
from dash import Dash, html
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP


class Section(ABC):
    def __init__(self,
                 gapp) -> None:
        self.gapp = gapp
        self.settings = gapp.settings
        self.app: Dash = gapp.app
        self.sop_db: SOP_DB = gapp.sop_db
        self.kin_db: KIN_DB = gapp.kin_db
        self.sim_db: SIM_DB = gapp.sim_db
        self.pp_sim_db: SIM_DB | None = getattr(gapp, 'pp_sim_db', None)
        self.init_SOP: SOP = gapp.init_SOP
        self.n_plots = 0
        self.species: list[str] = gapp.species
        self.register_callbacks()

    @property
    @abstractmethod
    def layout(self) -> html.Div:
        """Create the layout for the section."""
        pass

    @abstractmethod
    def register_callbacks(self):
        """Register the callbacks for the section."""
        pass
