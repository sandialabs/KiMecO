from abc import ABC, abstractmethod
from logging import Logger
from typing import Any
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.enums import ElementStatus, Pclass, Ptype
from kimeco.generation import Generation
from kimeco.parameters import SOP
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.scoring_f.scoring import Scoring
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
import numpy as np
from numpy.typing import NDArray
from kimeco.sensitivity.linear import Linear
from kimeco.database.kimeco_db import dbs


class GeneticAlgorithm(ABC):
    """This class cannot be instanciated directly,
    unless all abstract methods are overwritten.
    It is the receipe for a GA object that
    should be inherited by those.

    Args:
        ABC (metaclass): Make the Scoring class abstract.
    """
    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_el: Element,
                 input_tpl: list[str],
                 location: str,
                 klog: Logger
                 ) -> None:
        self.klog: Logger = klog
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.sf: Scoring = sf
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.f_el: Element = f_el
        self.losers: NDArray = np.zeros(
            shape=(
                self.settings['n_elem'],
                len(self.sop_db.columns)+1))
        self.input_tpl: list[str] = input_tpl
        self.gen_0 = Generation(
            elements=[f_el],
            settings=settings,
            rc_tpl=input_tpl,
            loc=location,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            sf=sf,
            pert=pert,
            klog=klog)
        self.loc: str = location
        self.goat: list[Element] = [f_el]
        self.__converged: dict[str, bool] = {}
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.old_means: dict[str, float] = {}
        self.old_stds: dict[str, float] = {}

    @property
    def goat_scores(self):
        return [el.score for el in self.goat]

    @property
    def converged(self) -> bool:
        if Generation.total() < 2:
            return False
        for conv in self.__converged.values():
            if not conv:
                return False
        return True

    def actualize_conv(self) -> None:
        """Actualize the convergence of the perturbed parameters
        """
        for key in self.means:
            if key not in self.__converged:
                self.__converged[key] = False
            # Find the type of parameter
        for key in self.old_means:
            for ptype in Ptype:
                if ptype.value in key.split(dbs)[1]:
                    break
            if ptype.value in Pclass.ADDITIVE.value:
                mean_thresh: float = self.settings[f'conv_{ptype.value}']
                std_thresh: float = self.settings[f'conv_{ptype.value}']
                m_change: float = self.means[key] - self.old_means[key]
                s_change: float = self.stds[key] - self.stds[key]
            else:
                mean_thresh = self.settings['param_conv']
                std_thresh = self.settings['param_conv']
                m_change: float = self.means[key]/self.old_means[key]
                s_change: float = self.stds[key]/self.stds[key]
            if abs(m_change) < mean_thresh and abs(s_change) < std_thresh:
                self.__converged[key] = True
            else:
                self.__converged[key] = False

    def write_goat_update(self) -> None:
        goat_line: str = ''
        for el in self.goat:
            goat_line += f'{el.gen}_{el.id} '
        goat_line += '\n'

        with open(self.loc + '/goat.txt', 'w') as f:
            f.write(goat_line)

    def print_stats(self) -> None:
        line_tpl = '{name:<15}{mean:>10} ± {std:<10}{status:>20}'
        msg = '\n'
        msg += line_tpl.format(
            name='PARAMETER',
            mean='MEAN',
            std='STD',
            status='STATUS') + '\n'
        for k, mean in self.means.items():
            std: float = self.stds[k]
            if mean >= 1000:
                str_mean: str = f"{mean:-9.2E}"
                str_std: str = f"{std:9.2E}"
            else:
                str_mean: str = f"{mean:-10.2f}"
                str_std: str = f"{std:10.2f}"
            if self.__converged[k]:
                status = 'CONVERGED'
            else:
                status = 'NOT CONVERGED'
            msg += line_tpl.format(
                name=k,
                mean=str_mean,
                std=str_std,
                status=status) + '\n'
        self.klog.info(msg)

    def write_score_update(self,
                           gen: Generation) -> None:
        """Write the next line in score_info

        Args:
            gen (Generation): next generation
        """
        score_line_tpl = '{gen_id:>10}{best_score:>15}{score_avrg:>15}\n'
        if gen.id == 1:
            with open(self.loc + '/score_info.txt', 'w') as f:
                f.write(score_line_tpl.format(
                        gen_id='GEN_ID',
                        best_score='BEST SCORE',
                        score_avrg='GOAT AVERAGE'))
        goat_avrg = np.average([el.score for el in self.goat])
        with open(self.loc + '/score_info.txt', 'a') as f:
            f.write(score_line_tpl.format(
                gen_id=f"G{gen.id:04d}",
                best_score=f"{gen.best_score:.3f}",
                score_avrg=f"{goat_avrg:.3f}"))

    def is_generation_finished(self,
                               gen_id: int) -> bool:
        """Check if a generation is finished.

        Args:
            gen_id (int): Generation id

        Returns:
            bool: Wether it is finished
        """
        gen_name: str = f"G{gen_id:04d}"
        if self.sop_db.table_exists(gen_name) and\
           self.kin_db.table_exists(gen_name) and\
           self.sim_db.table_exists(gen_name):
            sop_ids = set(self.sop_db.get_column(
                table=gen_name,
                column_name='id'))
            kin_ids = set(self.kin_db.get_column(
                table=gen_name,
                column_name='kin_id'))
            tmp = np.array(self.sim_db.get_column(
                table=gen_name,
                column_name='sim_id'))//len(self.settings['exp_profiles'])
            sim_ids = set(tmp.tolist())
            if sop_ids == kin_ids == sim_ids:
                return True
            else:
                return False
        else:
            return False

    def get_gen_one(self) -> tuple[dict[int, Element], list[Element]]:
        """Create the first generation from the initial element

        Returns:
            tuple[dict[int, Element], list[Element]]: _description_
        """
        next_elements: list[Element] = [self.f_el]
        prev_elements: dict[int, Element] = {}
        next_gen_id: int = Generation.total()
        next_gen_name: str = f"G{next_gen_id:04d}"
        if self.is_generation_finished(next_gen_id):
            sop_ids: list[Any] = self.sop_db.get_column(
                table=next_gen_name,
                column_name='id')
            if len(sop_ids) == self.settings['n_elem']-1:
                rows = np.array(
                    self.sop_db.get_table(table=f"G{next_gen_id:04d}")
                                        )
                for e_id, row in zip(sop_ids, rows):
                    next_elements.append(
                        Element(
                            sop=SOP.from_db_row(
                                sop_tpl=self.f_el.sop,
                                row=row[1:].tolist()
                            ),
                            id=e_id,
                            gen=next_gen_id,
                            status=ElementStatus.DONE.value))
            else:
                if self.sop_db.table_exists(next_gen_name):
                    self.sop_db.wipe_table(next_gen_name)
                if self.kin_db.table_exists(next_gen_name):
                    self.kin_db.wipe_table(next_gen_name)
                if self.sim_db.table_exists(next_gen_name):
                    self.sim_db.wipe_table(next_gen_name)
                next_elements.extend([
                    Element(
                        sop=self.pert.perturb(sop=self.f_el.sop),
                        id=id,
                        gen=next_gen_id)
                    for id in range(1, self.settings['n_elem'])])
        else:
            if self.sop_db.table_exists(next_gen_name):
                self.sop_db.wipe_table(next_gen_name)
            if self.kin_db.table_exists(next_gen_name):
                self.kin_db.wipe_table(next_gen_name)
            if self.sim_db.table_exists(next_gen_name):
                self.sim_db.wipe_table(next_gen_name)
            next_elements.extend([
                Element(
                    sop=self.pert.perturb(sop=self.f_el.sop),
                    id=id,
                    gen=next_gen_id)
                for id in range(1, self.settings['n_elem'])])

        for id in range(self.settings['n_elem']):
            prev_elements[id] = self.f_el
        return prev_elements, next_elements

    def get_next_gen(self,
                     gen: Generation):
        """Create the first generation from the initial element

        Returns:
            tuple[dict[int, Element], list[Element]]: _description_
        """
        next_elements: list[Element] = []
        prev_elements: dict[int, Element] = {}
        next_gen_id: int = Generation.total()
        next_gen_name: str = f"G{next_gen_id:04d}"
        if self.is_generation_finished(next_gen_id):
            sop_ids: list[Any] = self.sop_db.get_column(
                table=next_gen_name,
                column_name='id')
            rows = np.array(
                self.sop_db.get_table(table=f"G{next_gen_id:04d}")
                                    )
            for el_id in range(self.settings['n_elem']):
                if el_id in sop_ids:
                    row = rows[rows[:, 0] == el_id][0]
                    next_elements.append(
                        Element(
                            sop=SOP.from_db_row(
                                sop_tpl=self.f_el.sop,
                                row=row[1:].tolist()
                            ),
                            id=el_id,
                            gen=next_gen_id,
                            status=ElementStatus.DONE.value))
                elif el_id in [el.id for el in gen.elements]:
                    el_index: int = [el.id for el in gen.elements].index(el_id)
                    next_elements.append(gen.elements[el_index])
                else:
                    msg: str = f'Element {el_id} not found in db or prev. gen'
                    raise TypeError(msg)
        else:
            prev_elements, next_elements = self.create_next_gen(gen=gen)
        return prev_elements, next_elements

    def run(self) -> None:
        """Run the genetic algorythm to optimize an ensemble of elements
        """
        self.gen_0.run()
        prev_elements: dict[int, Element]
        new_elements: list[Element]
        prev_elements, new_elements = self.get_gen_one()
        while (not self.converged and
               Generation.total() < self.settings['max_gen']):
            new_gen = Generation(
                elements=new_elements,
                settings=self.settings,
                rc_tpl=self.input_tpl,
                loc=self.loc,
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                previous_el=prev_elements
                )
            new_gen.run()
            # Update the goat list
            self.update_goat(new_els=new_gen.elements)
            if new_gen.id > 1:
                self.old_means = self.means
                self.old_stds = self.stds
            self.means, self.stds = self.get_stats(
                elements=self.goat
                )
            # Actualize which parameter is converged
            self.actualize_conv()
            self.write_score_update(gen=new_gen)
            if new_gen.id > 1:
                self.print_stats()
            if not self.converged:
                prev_elements, new_elements = self.get_next_gen(gen=new_gen)
                if new_gen.id % self.settings['SA_freq'] == 0 and\
                   new_gen.id >= self.settings['SA_start']:
                    self.klog.info('On-the-fly sensitivity analysis.')
                    sensitivity = Linear(
                        elements=self.goat,
                        settings=self.settings,
                        rc_tpl=self.input_tpl,
                        loc=self.loc,
                        sf=self.sf,
                        pert=self.pert,
                        klog=self.klog)
                    sensitivity.run()
                    new_params = [
                        p for p in sensitivity.selected
                        if p not in self.settings['only_perturb']
                                  ]
                    new_p: bool = len(new_params) > 0
                    for p in new_params:
                        self.settings['only_perturb'].append(p)
                    if new_p:
                        msg = 'Perturbing the following new parameters:\n'
                        msg += "{}".format(new_params).replace("'", '"')
                        self.klog.info(msg)
        self.klog.info('Run Sucessful.')
        self.klog.info(f'Termination at generation {new_gen.id}')
        self.klog.info(f'Final score: {new_gen.best_score}')

    def update_goat(self,
                    new_els: list[Element]) -> None:
        replaced = 0
        added = 0
        # ordered elements
        o_els: list[Element] = sorted(
                new_els, key=lambda el: el.score
                )
        # Add elements in goat as long as it's too short
        if len(self.goat) < self.settings['goat_length']:
            for el in o_els:
                self.goat.append(el)
                added += 1
                if len(self.goat) == self.settings['goat_length']:
                    break
        # Otherwise, update
        else:
            for el in o_els:
                if el in self.goat:
                    continue
                max_goat = max(self.goat_scores)
                if el.score < max_goat:
                    to_replace: int = self.goat_scores.index(max_goat)
                    self.goat[to_replace] = el
                    replaced += 1
            # Check if goat has been properly updated
            max_goat: float = max(self.goat_scores)
            for el in o_els:
                if el.score <= max_goat and el not in self.goat:
                    msg: str = 'Bug in GOAT update.'
                    raise ValueError(msg)
        goat_avrg = np.average([el.score for el in self.goat])
        self.klog.info(f'GOAT AVERAGE SCORE: {goat_avrg:>60.2f}')
        if added > 0:
            self.klog.info(f'GOATs ADDED: {added}')
        if replaced > 0:
            self.klog.info(f'GOATs REPLACED: {replaced}')
        self.write_goat_update()

    def get_stats(self,
                  elements: list[Element]) -> tuple[dict[str, float], dict[str, float]]:
        """Calculate the standard deviation of each key in the
        parameters_names dictionary across all SOP objects.

        Returns:
            Dict[str, float]: Dictionary with the mean values for each key.
            Dict[str, float]:
                Dictionary with the standard deviation for each key.
        """

        sop_list: list[SOP] = [
            el.sop for el in elements
            ]

        # Initialize dictionaries to hold the sum of values,
        # sum of squared values, and a count of SOPs
        values: dict[str, list[float]] = {}
        means: dict[str, float] = {}
        stds: dict[str, float] = {}

        # Iterate through each SOP object
        for sop in sop_list:
            parameters: dict[str, Any] = sop.parameters_names
            for key, value in parameters.items():
                if key not in self.settings['only_perturb']:
                    continue
                # for ptype in Ptype:
                #     if ptype.value in key.split(dbs)[1]:
                #         break
                if key not in values:
                    values[key] = [value]
                else:
                    values[key].append(value)

        for key, vals in values.items():
            means[key] = float(np.average(vals))
            stds[key] = float(np.std(vals))
        return means, stds

    @abstractmethod
    def isconverged(self,
                    gen: Generation
                    ) -> bool:
        """Decide if a generation is converged or no
        depending on the algorythm criteria.

        Args:
            gen (Generation): Previous generation

        Returns:
            bool: whether is converged
        """
        pass

    @abstractmethod
    def create_next_gen(self,
                        gen: Generation
                        ) -> tuple[dict[int, Element], list[Element]]:
        """Return the list of elements of the next generation.
        Important: reset the Element.__id before creating
        the elements.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Element]: Elements for the next generation
        """
        pass
