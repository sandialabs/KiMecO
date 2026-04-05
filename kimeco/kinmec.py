import re
from typing import Any, Sequence
import cantera as ct
from copy import deepcopy
from kimeco.cantera.customrate import MessData, MessRate
from scipy.constants import Avogadro
import numpy as np
from numpy.typing import NDArray
from kimeco.bimolecular import Bimolecular
from kimeco.parameters import SOP
from kimeco.well import Well
from kimeco.templates.ct_reaction_tpl import reaction_yaml


class KiMec:
    def __init__(self,
                 file: str,
                 settings: dict[str, Any]) -> None:
        """Prepare the kinetic mechanism to be updated
        by MESS rate coefficients

        Args:
            file (str): path to the yaml mechanism
            settings (dict[str, Any]): user input
            sop_tpl (SOP | None): any SOP object corresponding to the system
                (the value of the parameters don't matter)
        """
        self.settings: dict[str, Any] = settings
        self.SOP: SOP
        self.file: str = file
        if settings['postprocess']:
            self.pres: list[float] = settings['pp_pres']
            self.temp: list[float] = settings['pp_temp']
        else:
            self.pres: list[float] = settings['rc_pres']
            self.temp: list[float] = settings['rc_temp']
        self.mech: ct.Solution = ct.Solution(file)
        self.species = [sp for sp in self.mech.species()]
        self.reactions = [rc for rc in self.mech.reactions()]
        # Create a yaml template for the rate coefficients of a reaction
        self.rc_tpl: str = ''
        for pindex in range(len(self.pres)):
            for tindex in range(len(self.temp)):
                self.rc_tpl += f'rc_{pindex}_{tindex}: ' +\
                                '{rates[' + f'{pindex}][{tindex}]' + '}' + '\n'
        self.new_reactions_tpls: dict[tuple[str, str], str] = {}

    def add_SOP(self, sop: SOP) -> None:
        """Add the SOP to the KiMec object to be able to create the reaction
        templates.

        Args:
            sop (SOP): SOP object corresponding to the system
        """
        self.SOP = sop

    def prepare_mech(self):
        """Prepare the mechanism for modifications of the reactions
        """
        self.add_species()
        self.create_reactions_templates()
        # Build PES-scoped placeholder arrays/maps until real rates are loaded.
        rc_by_pes: dict[int, NDArray] = {}
        tbl_map_by_pes: dict[int, dict[str, int]] = {}
        for pes_id in self.SOP.pes_ids:
            species_names: list[str] = self.SOP.species_names_in_pes(pes_id)
            tbl_map_by_pes[pes_id] = {
                name: idx
                for idx, name in enumerate(species_names)
            }
            n_species = len(species_names)
            rc_by_pes[pes_id] = np.zeros((
                len(self.pres),
                len(self.temp),
                n_species,
                n_species,
            ))
        new_reactions = self.create_reactions(
            rates_by_pes=rc_by_pes,
            tbl_map_by_pes=tbl_map_by_pes,
        )
        # remove redundant reactions
        for idx in reversed(self.find_redundant_idx(new_reactions)):
            self.reactions.pop(idx)

    def add_species(self) -> None:
        """Add the missing species from the SOP
        to the cantera Simulation.
        """
        mech_names: list[str] = [sp.name for sp in self.species]
        thermo = ct.NasaPoly2(self.species[0].thermo.min_temp,
                              self.species[0].thermo.max_temp,
                              self.species[0].thermo.reference_pressure,
                              self.species[0].thermo.coeffs)
        for specie in self.SOP.species:
            if specie not in mech_names:
                well: Well = self.SOP.items[specie]
                new_specie: ct.Species = ct.Species(name=well.name,
                                                    composition=well.compo
                                                    )
                new_specie.thermo = thermo
                self.species.append(new_specie)

    def find_redundant_idx(self,
                           new_reactions: list[ct.Reaction]
                           ) -> list[int]:
        reac_idx: list[int] = []
        for idx, reac in enumerate(self.reactions):
            for new_reac in new_reactions:
                if (
                    reac.reactants == new_reac.reactants
                    and reac.products == new_reac.products
                ):
                    reac_idx.append(idx)
        return reac_idx

    def create_reactions_templates(self) -> None:
        """Create the templates for every reactions to be updated.
        """
        # Create well to well reactions
        for reactant in self.SOP.wells:
            for product in self.SOP.wells:
                if reactant == product:
                    continue
                self.new_reactions_tpls[(reactant.name, product.name)] =\
                    self.create_reaction_template(reactant=reactant,
                                                  product=product)
        # Create well to bimolecular reactions
        for reactant in self.SOP.wells:
            for product in self.SOP.bimolecular:
                self.new_reactions_tpls[(reactant.name, product.name)] =\
                    self.create_reaction_template(reactant=reactant,
                                                  product=product)
        # Create bimolecular to well reactions
        for reactant in self.SOP.bimolecular:
            for product in self.SOP.wells:
                self.new_reactions_tpls[(reactant.name, product.name)] =\
                    self.create_reaction_template(reactant=reactant,
                                                  product=product)
        # Create bimolecular to bimolecular reactions
        for reactant in self.SOP.bimolecular:
            for product in self.SOP.bimolecular:
                if reactant == product:
                    continue
                self.new_reactions_tpls[(reactant.name, product.name)] =\
                    self.create_reaction_template(reactant=reactant,
                                                  product=product)

    def create_reaction_template(self,
                                 reactant: Well | Bimolecular,
                                 product: Well | Bimolecular
                                 ) -> str:
        """Create the template of a reaction where only the rate coefficient
        needs to be changed."""

        equation: str = self.get_reaction_eq(
            reactant=reactant,
            product=product)
        p_yaml: str = ''
        for p in self.settings["rc_pres"]:
            p_yaml += f'  - {round(p, 5)} {self.settings["pres_unit"]}' + '\n'
        t_yaml: str = ''
        for t in self.settings["rc_temp"]:
            t_yaml += f'  - {round(t, 5)} K' + '\n'
        reaction_tpl: str = reaction_yaml.format(equation=equation,
                                                 rates_yaml=self.rc_tpl,
                                                 p_yaml=p_yaml[:-1],
                                                 t_yaml=t_yaml[:-1])

        return reaction_tpl

    def get_reaction_eq(self,
                        reactant: Well | Bimolecular,
                        product: Well | Bimolecular
                        ) -> str:
        """Create the reation's equations (forward and reverse) and find
        appropriate units for the rate coefficient.

        Args:
            bar (Barrier): Barrier object corresponding to the reaction.

        Returns:
            tuple[list[str], list[str]]: units[forward, reverse]
                                         equations[f,r]
        """
        eq: str = ""
        if isinstance(reactant, Well):
            eq += reactant.name
        elif isinstance(reactant, Bimolecular):
            if not reactant.dummy:
                if not reactant.fragments:
                    raise ValueError(
                        f"Bimolecular {reactant.name} should have its "
                        "fragments defined."
                    )
                eq += f'{reactant.fragments[0].name}'
                eq += ' + '
                eq += f'{reactant.fragments[1].name}'
            else:
                try:
                    eq = ' + '.join(reactant.name.split('+'))
                except Exception:
                    raise ValueError(
                        f"Dummy bimolecular {reactant.name} should be named"
                        " as 'name1+name2' where name1 and name2 are the "
                        "names of the two fragments."
                    )

        eq += ' => '
        if isinstance(product, Well):
            eq += product.name
        elif isinstance(product, Bimolecular):
            if not product.dummy:
                if not product.fragments:
                    raise ValueError(
                        f"Bimolecular {product.name} should have its "
                        "fragments defined."
                    )
                eq += f'{product.fragments[0].name}'
                eq += ' + '
                eq += f'{product.fragments[1].name}'
            else:
                try:
                    eq = ' + '.join(product.name.split('+'))
                except Exception:
                    raise ValueError(
                        f"Dummy bimolecular {product.name} should be named"
                        " as 'name1+name2' where name1 and name2 are the "
                        "names of the two fragments."
                    )

        return eq

    def select_convert_rates(self,
                             reactant: Well | Bimolecular,
                             product: Well | Bimolecular,
                             units: str,
                             tbl_map: dict[str, int],
                             rc: NDArray) -> NDArray:
        """Adapt Mess reaction rate to cantera unit system.

        Args:
            reactant: (Well | Bimolecular): From
            product: (Well | Bimolecular): To
            units (str): unit of the rate coefficients
            tbl_map (dict[str, int]):
                key: name of specie
                value: index in mess output file
            rc (NDArray): all rate coefficients from KIN object

        Returns:
            list[str]: reaction rates of selected reaction.
        """
        From: int = tbl_map[reactant.name]
        To: int = tbl_map[product.name]
        rates: np.ndarray = deepcopy(rc[:, :, From, To])
        if 'm^3' in units:
            rates *= Avogadro / 1000

        return rates

    def _append_reaction_group(self,
                               reactants: Sequence[Well | Bimolecular],
                               products: Sequence[Well | Bimolecular],
                               units: str,
                               rates: NDArray,
                               tbl_map: dict[str, int],
                               mech_w_species: Any,
                               new_reactions: list[Any],
                               skip_identity: bool = False) -> None:
        """Create reactions for one reactant/product group.

        Missing species in the PES-local table map are skipped.
        """
        for reactant in reactants:
            for product in products:
                if skip_identity and reactant == product:
                    continue
                if reactant.name not in tbl_map or product.name not in tbl_map:
                    continue
                new_reactions.append(ct.Reaction.from_yaml(
                    self.new_reactions_tpls[
                        (reactant.name, product.name)
                        ].format(
                        rates=self.select_convert_rates(
                            reactant=reactant,
                            product=product,
                            units=units,
                            tbl_map=tbl_map,
                            rc=rates
                        )
                    ),
                    mech_w_species)
                )

    def create_reactions(self,
                         rates_by_pes: dict[int, NDArray],
                         tbl_map_by_pes: dict[int, dict[str, int]]
                         ):
        """Create cantera reaction objects with updates rate coefficients

        Args:

            rates_by_pes (dict[int, NDArray]): PES-scoped rates arrays
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped map linking
                indexes to species names

        Returns:
            list: list of cantera reaction objects
        """
        # Mechanism with all the new species
        mech_w_species: Any = ct.Solution(
            thermo="ideal-gas",
            kinetics="gas",
            species=self.species,
            reactions=self.reactions)
        new_reactions: list[Any] = []

        for pes_id in self.SOP.pes_ids:
            if pes_id not in rates_by_pes or pes_id not in tbl_map_by_pes:
                raise ValueError(
                    f"Missing rates or tbl_map for PES {pes_id} in the provided "
                    "rates. Check that the KIN_DB contains the appropriate "
                    "table name."
                )
            pes_rates = rates_by_pes[pes_id]
            pes_tbl_map = tbl_map_by_pes[pes_id]
            wells = self.SOP.wells_in(pes_id)
            bimolecular = self.SOP.bimols_in(pes_id)
            self._append_reaction_group(
                reactants=wells,
                products=wells,
                units="s^-1",
                rates=pes_rates,
                tbl_map=pes_tbl_map,
                mech_w_species=mech_w_species,
                new_reactions=new_reactions,
                skip_identity=True,
            )
            self._append_reaction_group(
                reactants=wells,
                products=bimolecular,
                units="s^-1",
                rates=pes_rates,
                tbl_map=pes_tbl_map,
                mech_w_species=mech_w_species,
                new_reactions=new_reactions,
            )
            self._append_reaction_group(
                reactants=bimolecular,
                products=wells,
                units="m^3/s/kmol",
                rates=pes_rates,
                tbl_map=pes_tbl_map,
                mech_w_species=mech_w_species,
                new_reactions=new_reactions,
            )
            self._append_reaction_group(
                reactants=bimolecular,
                products=bimolecular,
                units="m^3/s/kmol",
                rates=pes_rates,
                tbl_map=pes_tbl_map,
                mech_w_species=mech_w_species,
                new_reactions=new_reactions,
                skip_identity=True,
            )
        return new_reactions

    def get_updated_mech(self,
                         rates_by_pes: dict[int, list[Any]],
                         tbl_map_by_pes: dict[int, dict[str, int]]
                         ):
        """Get a cantera mechanism with updated rate coefficients
        Args:
            rates_by_pes (dict[int, list[Any]]): PES-scoped rates arrays
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped map linking
                indexes to species names
        """

        np_rates_by_pes = {
            int(pes_id): np.array(pes_rates)
            for pes_id, pes_rates in rates_by_pes.items()
        }
        new_reactions = self.create_reactions(
            rates_by_pes=np_rates_by_pes,
            tbl_map_by_pes=tbl_map_by_pes,
        )
        return ct.Solution(
            thermo="ideal-gas",
            kinetics="gas",
            species=self.species,
            reactions=self.reactions + new_reactions)
