import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Sequence, cast
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
from kimeco.writers.prompt_collector import (
    PromptChannel, is_prompt_run, prompt_to_names_by_pes)

#: KIN rate coefficient of a bimolecular reactant (cm^3 molecule^-1 s^-1,
#: as MESS prints it) times this factor gives Cantera's m^3 kmol^-1 s^-1.
_BIMOL_KIN_TO_CANTERA: float = Avogadro / 1000


def _species_multiset(names: Sequence[str]) -> tuple[tuple[str, int], ...]:
    """Species names as a multiset: sorted ``(name, count)`` pairs.

    The same species in another order give the same multiset, so it is the
    key that decides which prompt channels are summed into one reaction.

    Args:
        names (Sequence[str]): species names, possibly repeated.

    Returns:
        tuple[tuple[str, int], ...]: the sorted ``(name, count)`` pairs.
    """
    return tuple(sorted(Counter(names).items()))


@dataclass(frozen=True)
class MergedPromptReaction:
    """One prompt reaction of the Cantera mechanism (prompt mode).

    The prompt channels (``PromptChannel``) whose reactant species and
    product species are the same multisets give one irreversible reaction,
    whose rate coefficient is the sum of theirs. For example the
    thermalised channel ``CH2CHCH2CH3+H -> CH2CHCHCH3+H2`` of one PED PES
    and the channel ``CH2CHCH2CH3+H -> H2+CH2CHCHCH3`` of another (same
    products in another order) give one reaction.

    Attributes:
        reactants: names of the fragments of the PED reactant (its SOP
            ``Bimolecular``), in SOP order: the reactant side of the
            forward thermal reaction that the prompt reactions replace.
        products: final products of the first channel
            (``PromptChannel.product_fragments``), possibly three.
        channels: the summed channels, in fixed-set order.
    """
    reactants: tuple[str, ...]
    products: tuple[str, ...]
    channels: tuple[PromptChannel, ...]

    @property
    def equation(self) -> str:
        """Cantera equation of the reaction, irreversible (``=>``), e.g.
        ``CH2CHCH2CH3 + H => H2 + CH2CHCHCH2 + H``."""
        return (' + '.join(self.reactants) + ' => '
                + ' + '.join(self.products))


class KiMec:
    #: Prompt channels of the run (``PromptChannel.fixed_set`` of the SOP),
    #: set by ``create_reactions_templates`` in prompt mode
    #: (``is_prompt_run`` of the settings). These class-level defaults are
    #: empty, so non-prompt runs and objects built without ``__init__`` see
    #: no prompt data.
    prompt_channels: tuple[PromptChannel, ...] = ()
    #: Prompt reactions built from ``prompt_channels`` (same-equation
    #: channels summed), set with them.
    merged_prompt_reactions: tuple[MergedPromptReaction, ...] = ()
    #: Reaction template of each prompt reaction, keyed by its equation
    #: (``MergedPromptReaction.equation``), set with them.
    merged_prompt_tpls: dict[str, str]

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
            self.pres: list[float] = settings.get('rc_pres', [])
            self.temp: list[float] = settings.get('rc_temp', [])
        ct_any: Any = ct
        self.mech: Any = ct_any.Solution(file)
        self.species = [sp for sp in self.mech.species()]
        self.reactions = [rc for rc in self.mech.reactions()]
        # Create a yaml template for the rate coefficients of a reaction
        self.rc_tpl: str = self._build_rc_tpl()
        self.new_reactions_tpls: dict[tuple[str, str], str] = {}

    def _build_rc_tpl(self) -> str:
        """Build the YAML block mapping each (pressure, temperature) point of
        the active grid to a ``{rates[p][t]}`` substitution field.
        """
        rc_tpl: str = ''
        for pindex in range(len(self.pres)):
            for tindex in range(len(self.temp)):
                rc_tpl += f'rc_{pindex}_{tindex}: ' +\
                    '{rates[' + f'{pindex}][{tindex}]' + '}' + '\n'
        return rc_tpl

    def add_SOP(self, sop: SOP) -> None:
        """Add the SOP to the KiMec object to be able to create the reaction
        templates.

        Args:
            sop (SOP): SOP object corresponding to the system
        """
        self.SOP = sop

    def prepare_mech(self):
        """Prepare the mechanism for modifications of the reactions.

        Adds the missing species, builds the reaction templates, then builds
        every new reaction once with zero rates and removes the base
        reactions they replace. In prompt mode the placeholder tables of the
        PED PESs are extended with the prompt to_names (same layout as
        ``RateCo.load_rates_from_db``), so the prompt reactions replace
        their base reactions too.
        """
        self.add_species()
        self.create_reactions_templates()
        # Build PES-scoped placeholder arrays/maps until real rates are loaded.
        rc_by_pes: dict[int, NDArray] = {}
        tbl_map_by_pes: dict[int, dict[str, int]] = {}
        # {PED PES id: prompt to_names after its species}: empty outside
        # prompt mode.
        prompt_names: dict[int, list[str]] = prompt_to_names_by_pes(
            list(self.prompt_channels))
        for pes_id in self.SOP.pes_ids:
            species_names: list[str] = (self.SOP.species_names_in_pes(pes_id)
                                        + prompt_names.get(pes_id, []))
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
        # create_reactions appends the prompt reactions (one per
        # MergedPromptReaction, none outside prompt mode) after the thermal
        # ones: split them, as the two kinds are matched differently.
        n_thermal: int = (len(new_reactions)
                          - len(self.merged_prompt_reactions))
        # remove redundant reactions
        for idx in reversed(self.find_redundant_idx(
                new_reactions[:n_thermal],
                prompt_reactions=new_reactions[n_thermal:])):
            self.reactions.pop(idx)

    def add_species(self) -> None:
        """Add the missing species from the SOP
        to the cantera Simulation.
        """
        mech_names: list[str] = [sp.name for sp in self.species]
        ct_any: Any = ct
        thermo = ct_any.NasaPoly2(self.species[0].thermo.min_temp,
                                  self.species[0].thermo.max_temp,
                                  self.species[0].thermo.reference_pressure,
                                  self.species[0].thermo.coeffs)
        for specie in self.SOP.species:
            if specie not in mech_names:
                item = self.SOP.items[specie]
                if not isinstance(item, Well):
                    msg: str = f"Only wells can be added as new "
                    msg += f"species. '{specie}' is not a well."
                    raise ValueError(msg)
                well: Well = cast(Well, item)
                new_specie: Any = ct_any.Species(name=well.name,
                                                 composition=well.compo
                                                 )
                new_specie.thermo = thermo
                self.species.append(new_specie)

    def find_redundant_idx(self,
                           new_reactions: Sequence[Any],
                           prompt_reactions: Sequence[Any] = ()
                           ) -> list[int]:
        """Indexes of the base reactions that the new reactions replace.

        The two kinds of new reactions are matched with different keys,
        reversible (``<=>``) or not (``=>``) alike:

        - a thermal (MESS) reaction replaces a base reaction
          (``self.reactions``) with the same Cantera ``reactants`` and
          ``products`` (``_thermal_species``): a three-body collider is left
          out, so the MESS ``H + O2 => HO2`` replaces the base
          ``H + O2 + AR <=> HO2 + AR``;
        - a prompt reaction (one per ``MergedPromptReaction``) replaces a
          base reaction with the same species, an explicit collider included
          on both (``_participant_species``): ``X + H => Y + Z + H`` replaces
          the same equation, read as three-body or as elementary, but not
          ``X => Y + Z``.

        Each index appears once, in ascending order, so popping them in
        reverse order removes exactly these base reactions, even when several
        new reactions match the same one.

        Args:
            new_reactions (Sequence[Any]): the new thermal Cantera reactions
                (all of them for callers outside prompt mode).
            prompt_reactions (Sequence[Any]): the new prompt Cantera
                reactions; none by default.

        Returns:
            list[int]: indexes in ``self.reactions``, ascending.
        """
        thermal_keys: set[tuple[tuple[tuple[str, float], ...], ...]] = {
            self._thermal_species(new_reac) for new_reac in new_reactions}
        prompt_keys: set[tuple[tuple[tuple[str, float], ...], ...]] = {
            self._participant_species(new_reac)
            for new_reac in prompt_reactions}
        return [idx for idx, reac in enumerate(self.reactions)
                if self._thermal_species(reac) in thermal_keys
                or (prompt_keys
                    and self._participant_species(reac) in prompt_keys)]

    @staticmethod
    def _thermal_species(reaction: Any
                         ) -> tuple[tuple[tuple[str, float], ...], ...]:
        """Reactant and product species of a Cantera reaction as Cantera
        reads them (``reactants``/``products``, any collider left out), as
        sorted ``(name, coefficient)`` pairs: the key that matches a thermal
        (MESS) reaction to the base reactions it replaces.

        Args:
            reaction (Any): a Cantera reaction.

        Returns:
            tuple[tuple[tuple[str, float], ...], ...]: (reactant pairs,
                product pairs), each sorted by species name.
        """
        return (tuple(sorted(reaction.reactants.items())),
                tuple(sorted(reaction.products.items())))

    @staticmethod
    def _participant_species(reaction: Any
                             ) -> tuple[tuple[tuple[str, float], ...], ...]:
        """Reactant and product species of a Cantera reaction, collider
        species included, as sorted ``(name, coefficient)`` pairs: the key
        that matches a prompt reaction to the base reactions it replaces.

        Cantera (>= 3.0) reads a species written on both sides of an
        equation, e.g. ``H`` in ``CH2CHCH2CH3 + H => CH2CHCHCH2 + H2 + H``,
        as the collider of a three-body reaction and leaves it out of the
        ``reactants``/``products`` dicts, which then equal those of
        ``CH2CHCH2CH3 => CH2CHCHCH2 + H2``. Such an explicit collider (a
        species, with ``third_body.mass_action``: the rate is proportional
        to its concentration) is put back once on each side, so the two
        reactions differ, and a three-body reaction equals the same
        equation read as elementary (``type: elementary`` keeps the species
        in the dicts).

        The generic collider ``M`` (``A + M <=> B + M``) and a falloff
        collider (``A (+M) <=> B (+M)``, ``A (+AR) <=> B (+AR)``: no mass
        action) only tell the pressure dependence, so they are left out, as
        in ``_thermal_species``.

        Args:
            reaction (Any): a Cantera reaction.

        Returns:
            tuple[tuple[tuple[str, float], ...], ...]: (reactant pairs,
                product pairs), each sorted by species name.
        """
        reactants: dict[str, float] = dict(reaction.reactants)
        products: dict[str, float] = dict(reaction.products)
        # third_body: None when the reaction has no collider.
        third_body: Any = reaction.third_body
        if (third_body is not None and third_body.mass_action
                and third_body.name != 'M'):
            collider: str = third_body.name
            reactants[collider] = reactants.get(collider, 0.0) + 1.0
            products[collider] = products.get(collider, 0.0) + 1.0
        return (tuple(sorted(reactants.items())),
                tuple(sorted(products.items())))

    def create_reactions_templates(self) -> None:
        """Create the templates for every reactions to be updated.

        The thermal reactions of every (reactant, product) pair of the SOP,
        then, in prompt mode, the prompt reactions
        (``_create_prompt_reactions_templates``).
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
        self._create_prompt_reactions_templates()

    def _prompt_channels(self) -> list[PromptChannel]:
        """The prompt channels of the run, or none outside prompt mode.

        The only prompt-mode gate of KiMec: prompt mode needs the settings
        to have ``use_automech`` and ``prompt_reactions`` true
        (``is_prompt_run``). Objects without settings (built without
        ``__init__``) and partial settings (GUI) are never in prompt mode,
        and ``SOP.pes_file_data`` is read only in prompt mode.

        Returns:
            list[PromptChannel]: ``PromptChannel.fixed_set`` of the SOP, or
            an empty list.
        """
        settings: dict[str, Any] | None = getattr(self, 'settings', None)
        if not settings or not is_prompt_run(settings):
            return []
        return PromptChannel.fixed_set(self.SOP)

    def _merge_prompt_channels(
            self,
            channels: Sequence[PromptChannel]
            ) -> tuple[MergedPromptReaction, ...]:
        """Group the prompt channels into prompt reactions.

        Channels with the same reactant multiset and product multiset
        (``_species_multiset``) form one reaction, in the order the first
        channel of each reaction appears. The reactants are the fragments of
        the PED reactant's SOP Bimolecular.

        Args:
            channels (Sequence[PromptChannel]): the channels, in fixed-set
                order.

        Returns:
            tuple[MergedPromptReaction, ...]: the prompt reactions.

        Raises:
            ValueError: a PED reactant is not a non-dummy Bimolecular with
                fragments in the SOP (refused when the MESS inputs are
                read).
        """
        # {(reactant multiset, product multiset): (reactants, products,
        # channels)}, in first-seen order.
        groups: dict[
            tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]],
            tuple[tuple[str, ...], tuple[str, ...], list[PromptChannel]],
        ] = {}
        for channel in channels:
            item = self.SOP.items.get(channel.ped_reactant)
            if (not isinstance(item, Bimolecular) or item.dummy
                    or not item.fragments):
                raise ValueError(
                    f"Prompt reaction: the PED reactant "
                    f"'{channel.ped_reactant}' of PES {channel.ped_pes_id} "
                    "is not a Bimolecular with fragments in the SOP.")
            reactants = tuple(frag.name for frag in item.fragments)
            key = (_species_multiset(reactants),
                   _species_multiset(channel.product_fragments))
            if key not in groups:
                groups[key] = (reactants, channel.product_fragments, [])
            groups[key][2].append(channel)
        return tuple(
            MergedPromptReaction(reactants=reactants, products=products,
                                 channels=tuple(merged_channels))
            for reactants, products, merged_channels in groups.values())

    def _create_prompt_reactions_templates(self) -> None:
        """Set the prompt channels, the prompt reactions and their
        templates on the active grid (all empty outside prompt mode).

        Called by ``create_reactions_templates``, so a grid switch
        (``_sync_grid_to_rates``) rebuilds them too.
        """
        self.prompt_channels = tuple(self._prompt_channels())
        self.merged_prompt_reactions = self._merge_prompt_channels(
            self.prompt_channels)
        self.merged_prompt_tpls = {
            merged.equation: self._reaction_template(merged.equation)
            for merged in self.merged_prompt_reactions
        }

    def create_reaction_template(self,
                                 reactant: Well | Bimolecular,
                                 product: Well | Bimolecular
                                 ) -> str:
        """Create the template of a reaction where only the rate coefficient
        needs to be changed."""

        equation: str = self.get_reaction_eq(
            reactant=reactant,
            product=product)
        return self._reaction_template(equation)

    def _reaction_template(self,
                           equation: str) -> str:
        """Template of a ``Mess-data`` reaction on the active grid.

        Only the ``{rates[p][t]}`` fields remain to fill (``str.format``
        with ``rates=``); pressures are written in bar, temperatures in K.

        Args:
            equation (str): Cantera equation of the reaction.

        Returns:
            str: the YAML template of the reaction.
        """
        p_yaml: str = ''
        for p in self.pres:
            p_yaml += f'  - {round(p, 5)} bar' + '\n'
        t_yaml: str = ''
        for t in self.temp:
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
                    eq += ' + '.join(product.name.split('+'))
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
                               skip_identity: bool = False,
                               skip_pairs: Collection[tuple[str, str]] = ()
                               ) -> None:
        """Create reactions for one reactant/product group.

        Missing species in the PES-local table map are skipped.

        Args:
            skip_pairs (Collection[tuple[str, str]]): ``(reactant name,
                product name)`` pairs whose reaction is not built (prompt
                mode: the forward thermal reaction of a linked PED pair).
        """
        for reactant in reactants:
            for product in products:
                if skip_identity and reactant == product:
                    continue
                if (reactant.name, product.name) in skip_pairs:
                    continue
                if reactant.name not in tbl_map or product.name not in tbl_map:
                    continue
                ct_any: Any = ct
                new_reactions.append(ct_any.Reaction.from_yaml(
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

        In prompt mode the forward thermal reaction ``ped_reactant =>
        ped_product`` of each linked PED pair (a pair with at least one
        prompt channel) is not built: the prompt reactions replace it. Its
        reverse ``ped_product => ped_reactant`` is built as usual (MESS
        rate, not rescaled), so detailed balance between the two directions
        does not hold. The prompt reactions are appended after the thermal
        ones of every PES.

        Args:

            rates_by_pes (dict[int, NDArray]): PES-scoped rates arrays
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped map linking
                indexes to species names (prompt mode: extended rate tables
                of the PED PESs, see ``RateCo.load_rates_from_db``)

        Returns:
            list: list of cantera reaction objects

        Raises:
            ValueError: a PES is missing from the rates, or, in prompt mode,
                a PED PES table lacks the prompt to_names.
        """
        # Mechanism with all the new species
        ct_any: Any = ct
        mech_w_species: Any = ct_any.Solution(
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
            # Prompt mode: (ped_reactant, ped_product) of the linked PED
            # pairs of this PES, whose forward thermal reaction is replaced
            # by the prompt reactions (empty outside prompt mode).
            linked_pairs: set[tuple[str, str]] = {
                (channel.ped_reactant, channel.ped_product)
                for channel in self.prompt_channels
                if channel.ped_pes_id == pes_id
            }
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
                skip_pairs=linked_pairs,
            )
        new_reactions.extend(self._create_prompt_reactions(
            rates_by_pes=rates_by_pes,
            tbl_map_by_pes=tbl_map_by_pes,
            mech_w_species=mech_w_species,
        ))
        return new_reactions

    def _prompt_channel_rates(self,
                              channel: PromptChannel,
                              rates_by_pes: dict[int, NDArray],
                              tbl_map_by_pes: dict[int, dict[str, int]]
                              ) -> NDArray:
        """Rate coefficients of one prompt channel, in Cantera units.

        Read from the extended rate table of its PED PES at ``[ped_reactant,
        prompt to_name]`` and converted from KIN units (cm^3 molecule^-1
        s^-1, bimolecular reactant) to m^3 kmol^-1 s^-1.

        Args:
            channel (PromptChannel): the channel.
            rates_by_pes (dict[int, NDArray]): PES-scoped rates arrays.
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped maps.

        Returns:
            NDArray: a new ``(n_p, n_t)`` array.

        Raises:
            ValueError: the table of the PED PES lacks the PED reactant or
                the prompt to_name (a payload without the prompt names in
                prompt mode would otherwise lose the forward reaction).
        """
        tbl_map: dict[str, int] = tbl_map_by_pes[channel.ped_pes_id]
        to_name: str = channel.kin_row_to_name
        missing: list[str] = [name for name in (channel.ped_reactant, to_name)
                              if name not in tbl_map]
        if missing:
            raise ValueError(
                f"Prompt mode: the rate table of PES {channel.ped_pes_id} "
                f"has no {', '.join(missing)}. In prompt mode the table of "
                "a PED PES must list the prompt to_names of its channels "
                "after its species (RateCo.load_rates_from_db), otherwise "
                "the prompt reactions would have no rate.")
        rates: NDArray = rates_by_pes[channel.ped_pes_id]
        return (rates[:, :, tbl_map[channel.ped_reactant], tbl_map[to_name]]
                * _BIMOL_KIN_TO_CANTERA)

    def _create_prompt_reactions(self,
                                 rates_by_pes: dict[int, NDArray],
                                 tbl_map_by_pes: dict[int, dict[str, int]],
                                 mech_w_species: Any) -> list[Any]:
        """Cantera reactions of the prompt reactions (prompt mode).

        The rate of each ``MergedPromptReaction`` is the sum of its
        channels' rates, each converted to Cantera units first. A reaction
        whose rates are all zero is kept.

        Args:
            rates_by_pes (dict[int, NDArray]): PES-scoped rates arrays.
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped maps.
            mech_w_species (Any): Cantera Solution holding every species.

        Returns:
            list[Any]: the reactions, empty outside prompt mode.
        """
        ct_any: Any = ct
        reactions: list[Any] = []
        for merged in self.merged_prompt_reactions:
            total: NDArray = self._prompt_channel_rates(
                merged.channels[0], rates_by_pes, tbl_map_by_pes)
            for channel in merged.channels[1:]:
                total = total + self._prompt_channel_rates(
                    channel, rates_by_pes, tbl_map_by_pes)
            reactions.append(ct_any.Reaction.from_yaml(
                self.merged_prompt_tpls[merged.equation].format(rates=total),
                mech_w_species))
        return reactions

    def _sync_grid_to_rates(self,
                            np_rates_by_pes: dict[int, NDArray]) -> None:
        """Align the reaction templates with the (P, T) grid of the rates.

        The injected rate arrays are the source of truth for the grid
        dimensions. When they do not match the grid the templates were built
        with (for example postprocessing rates evaluated on the ``pp_*`` grid
        while the templates default to the ``rc_*`` grid), switch to the
        settings grid whose lengths match and rebuild the templates (the
        prompt reactions' templates too, in prompt mode).
        """
        if not np_rates_by_pes:
            return
        sample: NDArray = next(iter(np_rates_by_pes.values()))
        if sample.ndim != 4:
            return
        n_pres, n_temp = int(sample.shape[0]), int(sample.shape[1])
        if n_pres == len(self.pres) and n_temp == len(self.temp):
            return
        candidate_grids = (
            (self.settings.get('pp_pres', []),
             self.settings.get('pp_temp', [])),
            (self.settings.get('rc_pres', []),
             self.settings.get('rc_temp', [])),
        )
        for pres, temp in candidate_grids:
            if len(pres) == n_pres and len(temp) == n_temp:
                self.pres = list(pres)
                self.temp = list(temp)
                self.rc_tpl = self._build_rc_tpl()
                self.create_reactions_templates()
                return
        raise ValueError(
            f"Rate array grid ({n_pres} pressures x {n_temp} temperatures) "
            "does not match the 'rc' or 'pp' grids defined in the settings."
        )

    def get_updated_mech(self,
                         rates_by_pes: dict[int, list[Any]],
                         tbl_map_by_pes: dict[int, dict[str, int]]
                         ):
        """Get a cantera mechanism with updated rate coefficients

        In prompt mode the tables of the PED PESs are the extended rate
        tables of ``RateCo.load_rates_from_db`` and the mechanism holds the
        prompt reactions instead of the forward thermal reactions they
        replace; the thermal reverses are kept (see ``create_reactions``).

        Args:
            rates_by_pes (dict[int, list[Any]]): PES-scoped rates arrays
            tbl_map_by_pes (dict[int, dict[str, int]]): PES-scoped map linking
                indexes to species names
        """

        np_rates_by_pes = {
            int(pes_id): np.array(pes_rates)
            for pes_id, pes_rates in rates_by_pes.items()
        }
        self._sync_grid_to_rates(np_rates_by_pes)
        new_reactions = self.create_reactions(
            rates_by_pes=np_rates_by_pes,
            tbl_map_by_pes=tbl_map_by_pes,
        )
        ct_any: Any = ct
        return ct_any.Solution(
            thermo="ideal-gas",
            kinetics="gas",
            species=self.species,
            reactions=self.reactions + new_reactions)
