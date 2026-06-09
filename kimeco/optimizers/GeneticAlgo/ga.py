from abc import ABC, abstractmethod
from collections import defaultdict
from copy import deepcopy
import re
from kimeco.logger_config import KMOLogger
from typing import Any, List
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.enums import ModelStatus, Pclass, Ptype, RestartType
from kimeco.generation import Generation
from kimeco.parameters import SOP
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.scoring_f.scoring import Scoring
from kimeco.database.sop_db import SOP_DB
from kimeco.model import Model
import numpy as np
from kimeco.sensitivity.linear import Linear
from kimeco.database.kimeco_db import dbs
from kimeco.goat import GOATs


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
                 f_mdl: Model,
                 input_tpls: list[list[str]],
                 klog: KMOLogger
                 ) -> None:
        self.klog: KMOLogger = klog
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.sf: Scoring = sf
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.f_mdl: Model = f_mdl
        self.input_tpls: list[list[str]] = input_tpls
        self.new_gen_has_been_created = False
        self.gen_0 = Generation(
            models=[f_mdl],
            settings=settings,
            rc_tpls=input_tpls,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            sf=sf,
            pert=pert,
            klog=klog)
        self.loc: str = self.settings['workdir']
        # GOATs manager: if caller provided one, use it; otherwise create
        # a default GOATs instance that will persist to <location>/goats.txt
        self.goats = GOATs(
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db,
                wdir=self.loc
            )

        self.goat: list[Model] = []
        self.__converged: dict[str, bool] = {}
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.old_means: dict[str, float] = {}
        self.old_stds: dict[str, float] = {}

    @property
    def goat_scores(self) -> list[float]:
        return [mdl.score for mdl in self.goat]

    @property
    def converged(self) -> bool:
        avrg = float(np.average(self.goat_scores))
        if Generation.total() < 2:
            return False
        elif (all([goat.score < self.settings['max_score']
                  for goat in self.goat])
              and all([conv
                       for conv in self.__converged.values()])
              and avrg < self.settings['score_conv']):
            return True
        elif Generation.total() >= self.settings['max_gen']:
            self.klog.info(
                f'Reached {self.settings["max_gen"]} (max_gen) generations '
                'without convergence.'
            )
            return True
        else:
            return False

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
                s_change: float = self.stds[key] - self.old_stds[key]
            else:
                # Avoids dividing by 0
                if self.old_means[key] == 0 or\
                   self.old_stds[key] == 0:
                    self.__converged[key] = False
                    continue
                mean_thresh = self.settings['param_conv']
                std_thresh = self.settings['param_conv']
                m_change: float = abs(self.old_means[key]-self.means[key]
                                      )/self.old_means[key]
                s_change: float = abs(self.old_stds[key]-self.stds[key]
                                      )/self.old_stds[key]
            if abs(m_change) < mean_thresh and abs(s_change) < std_thresh:
                self.__converged[key] = True
            else:
                self.__converged[key] = False

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
                str_mean: str = f"{mean:-10.2E}"
                str_std: str = f"{std:10.2E}"
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

    def is_generation_finished(self,
                               gen_id: int) -> bool:
        """Check if a generation is finished.

        Args:
            gen_id (int): Generation id

        Returns:
            bool: Wether it is finished
        """
        # GA are sequential, if a new gen has been created,
        # the next one cannot be restarted from DB
        if self.new_gen_has_been_created:
            return False
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
            sim_ids = set(self.sim_db.get_column(
                table=gen_name,
                column_name='mdl_id'))
            if sop_ids == kin_ids == sim_ids:
                return True
            else:
                return False
        else:
            return False

    def get_gen_one(self) -> tuple[dict[int, Model], list[Model]]:
        """Create the first generation from the initial model

        Returns:
            tuple[dict[int, Model], list[Model]]: _description_
        """
        next_models: list[Model] = [self.f_mdl]
        prev_models: dict[int, Model] = {}
        next_gen_id: int = Generation.total()
        next_gen_name: str = f"G{next_gen_id:04d}"
        if self.is_generation_finished(next_gen_id):
            sop_ids: list[Any] = self.sop_db.get_column(
                table=next_gen_name,
                column_name='id')
            self.klog.debug(
                f'Found {len(sop_ids)} models for next generation in DB')
            if len(sop_ids) == self.settings['n_mdl']-1:
                self.klog.debug(
                    'Generation restarted from DB')
                if self.settings['restart'] == RestartType.RESCORE:
                    self.klog.debug(
                        'Rescoring only, no new calculations will be done.')
                rows = np.array(
                    self.sop_db.get_table(table=f"G{next_gen_id:04d}")
                                        )
                for e_id, row in zip(sop_ids, rows):
                    if self.settings['restart'] == RestartType.RESCORE:
                        next_models.append(
                            Model(
                                sop=SOP.from_db_row(
                                    sop_tpl=self.f_mdl.sop,
                                    row=row[1:].tolist()
                                ),
                                id=e_id,
                                gen=next_gen_id,
                                status=ModelStatus.RESCORE.value))
                    else:
                        next_models.append(
                            Model(
                                sop=SOP.from_db_row(
                                    sop_tpl=self.f_mdl.sop,
                                    row=row[1:].tolist()
                                ),
                                id=e_id,
                                gen=next_gen_id,
                                status=ModelStatus.DONE.value))
            else:
                self.klog.debug(
                    f'n_mdl requested but only {len(sop_ids)} found in DB.')
                self.klog.debug(
                    'Tables erased from DB and Genereation recreated.')
                if self.sop_db.table_exists(next_gen_name):
                    self.sop_db.wipe_table(next_gen_name)
                if self.kin_db.table_exists(next_gen_name):
                    self.kin_db.wipe_table(next_gen_name)
                if self.sim_db.table_exists(next_gen_name):
                    self.sim_db.wipe_table(next_gen_name)
                next_models.extend([
                    Model(
                        sop=self.pert.perturb(sop=deepcopy(self.f_mdl.sop)),
                        id=id,
                        gen=next_gen_id)
                    for id in range(1, self.settings['n_mdl'])])
        else:
            self.klog.debug(
                'Next generation not in DB. Creating it.')
            self.new_gen_has_been_created = True
            if self.settings['restart'] == RestartType.RESCORE:
                raise TypeError(
                    'Rescoring only but next generation not in DB.')
            if self.sop_db.table_exists(next_gen_name):
                self.sop_db.wipe_table(next_gen_name)
            if self.kin_db.table_exists(next_gen_name):
                self.kin_db.wipe_table(next_gen_name)
            if self.sim_db.table_exists(next_gen_name):
                self.sim_db.wipe_table(next_gen_name)
            next_models.extend([
                Model(
                    sop=self.pert.perturb(sop=deepcopy(self.f_mdl.sop)),
                    id=id,
                    gen=next_gen_id)
                for id in range(1, self.settings['n_mdl'])])

        for id in range(self.settings['n_mdl']):
            prev_models[id] = self.f_mdl
        return prev_models, next_models

    def get_next_gen(self,
                     gen: Generation):
        """Create the first generation from the initial model

        Returns:
            tuple[dict[int, Model], list[Model]]: _description_
        """
        next_models: list[Model] = []
        prev_models: dict[int, Model] = {}
        next_gen_id: int = Generation.total()
        next_gen_name: str = f"G{next_gen_id:04d}"
        if self.is_generation_finished(next_gen_id):
            sop_ids: list[Any] = self.sop_db.get_column(
                table=next_gen_name,
                column_name='id')
            self.klog.debug(
                f'Found {len(sop_ids)} models for next generation in DB')
            rows = np.array(
                self.sop_db.get_table(table=f"G{next_gen_id:04d}")
                                    )
            if self.settings['restart'] == RestartType.RESCORE:
                self.klog.debug(
                    'Rescoring only, no new calculations will be done.')
            for mdl_id in range(self.settings['n_mdl']):
                if mdl_id in sop_ids:
                    row = rows[rows[:, 0] == mdl_id][0]
                    if self.settings['restart'] == RestartType.RESCORE:
                        next_models.append(
                            Model(
                                sop=SOP.from_db_row(
                                    sop_tpl=self.f_mdl.sop,
                                    row=row[1:].tolist()
                                ),
                                id=mdl_id,
                                gen=next_gen_id,
                                status=ModelStatus.RESCORE.value))
                    else:
                        next_models.append(
                            Model(
                                sop=SOP.from_db_row(
                                    sop_tpl=self.f_mdl.sop,
                                    row=row[1:].tolist()
                                ),
                                id=mdl_id,
                                gen=next_gen_id,
                                status=ModelStatus.DONE.value))
                elif mdl_id in [mdl.id for mdl in gen.models]:
                    mdl_ids = [mdl.id for mdl in gen.models]
                    el_index: int = mdl_ids.index(mdl_id)
                    next_models.append(gen.models[el_index])
                else:
                    msg: str = f'Model {mdl_id} not found in db or prev. gen'
                    raise TypeError(msg)
        else:
            self.klog.debug(
                'Next generation not in DB. Creating it.')
            self.new_gen_has_been_created = True
            if self.settings['restart'] == RestartType.RESCORE:
                raise TypeError(
                    'Rescoring only but next generation not in DB.')
            if self.sop_db.table_exists(next_gen_name):
                self.sop_db.wipe_table(next_gen_name)
            if self.kin_db.table_exists(next_gen_name):
                self.kin_db.wipe_table(next_gen_name)
            if self.sim_db.table_exists(next_gen_name):
                self.sim_db.wipe_table(next_gen_name)
            prev_models, next_models = self.create_next_gen(gen=gen)
        return prev_models, next_models

    def run(self) -> None:
        """Run the genetic algorythm to optimize an ensemble of models
        """
        self.gen_0.run()
        self.update_goat(new_mdls=self.gen_0.models)
        self.means, self.stds = self.get_stats(
            models=self.goat
            )
        # Actualize which parameter is converged
        self.actualize_conv()
        # self.write_score_update(gen=self.gen_0)
        prev_models: dict[int, Model]
        new_models: list[Model]
        prev_models, new_models = self.get_gen_one()
        while (not self.converged and
               Generation.total() < self.settings['max_gen']):
            new_gen = Generation(
                models=new_models,
                settings=self.settings,
                rc_tpls=self.input_tpls,
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                previous_el=prev_models
                )
            new_gen.run()
            # Update the goat list
            self.update_goat(new_mdls=new_gen.models)
            # if new_gen.id > 1:
            self.old_means = self.means
            self.old_stds = self.stds
            self.means, self.stds = self.get_stats(
                models=self.goat
                )
            # Actualize which parameter is converged
            self.actualize_conv()
            # self.write_score_update(gen=new_gen)
            if new_gen.id > 1:
                self.print_stats()
            if not self.converged:
                prev_models, new_models = self.get_next_gen(gen=new_gen)
                if new_gen.id % self.settings['SA_freq'] == 0 and\
                   new_gen.id >= self.settings['SA_start'] and\
                   new_gen.id <= self.settings['SA_end']:
                    self.run_sensitivity(gen_id=new_gen.id)

        if self.converged:
            try:
                out_file = self.write_ga_rates_output()
                self.klog.info(
                    f'Convergence rate statistics written to {out_file}'
                )
            except Exception as exc:
                self.klog.warning(
                    'Failed to write GA convergence rate statistics: '
                    f'{exc}'
                )

        self.klog.info('Run Sucessful.')
        if Generation.total() > 1:
            self.klog.info(f'Termination at generation {new_gen.id}')
            self.klog.info(f'Final score: {new_gen.best_score}')

    @staticmethod
    def geometric_mean_and_std(
        values: list[float],
    ) -> tuple[float, float] | None:
        """Compute geometric mean/std from strictly positive values."""
        positives = [float(v) for v in values if float(v) > 0.0]
        if len(positives) == 0:
            return None
        logs = np.log(np.array(positives, dtype=float))
        gmean = float(np.exp(np.mean(logs)))
        gstd = float(np.exp(np.std(logs)))
        return gmean, gstd

    def _rate_conditions(self) -> tuple[list[float], list[float]]:
        if self.settings['postprocess']:
            pres = list(self.settings['pp_pres'])
            temp = list(self.settings['pp_temp'])
        else:
            pres = list(self.settings['rc_pres'])
            temp = list(self.settings['rc_temp'])
        return pres, temp

    def _eligible_models_for_rate_output(
        self,
    ) -> tuple[list[tuple[str, int, float]], int]:
        """Return eligible models from SOP DB and total scanned count.

        Scans all generation tables up to the last available generation,
        rebuilds each model SOP from DB rows, and selects models with
        finite mdl.score < max_score.
        """
        max_score = float(self.settings['max_score'])
        eligible: list[tuple[str, int, float]] = []
        total_scanned = 0

        gen_tables = [
            table
            for table in self.sop_db.tables.keys()
            if re.match(r'^G\d{4}$', table)
        ]
        if len(gen_tables) == 0:
            return eligible, total_scanned

        last_gen = max(int(table[1:]) for table in gen_tables)
        sorted_tables = sorted(
            [table for table in gen_tables if int(table[1:]) <= last_gen],
            key=lambda name: int(name[1:]),
        )

        for table in sorted_tables:
            rows = self.sop_db.get_table(table=table)
            for row in rows:
                total_scanned += 1
                mdl_id = int(row[0])
                sop = SOP.from_db_row(
                    sop_tpl=self.f_mdl.sop,
                    row=list(row[1:]),
                )
                mdl = Model(
                    sop=sop,
                    id=mdl_id,
                    gen=int(table[1:]),
                    status=ModelStatus.DONE.value,
                )
                if np.isfinite(mdl.score) and mdl.score < max_score:
                    eligible.append((table, mdl_id, mdl.score))
        eligible.sort(key=lambda v: (int(v[0][1:]), v[1]))
        return eligible, total_scanned

    @staticmethod
    def _format_geo_cell(value: tuple[float, float] | None) -> str:
        if value is None:
            return 'N/A'
        gmean, gstd = value
        return f'{gmean:.2e} ({gstd:.2f})'

    @staticmethod
    def _column_widths(rows: list[list[str]]) -> list[int]:
        """Return per-column widths from max cell length plus padding."""
        if len(rows) == 0:
            return []
        n_cols = max(len(row) for row in rows)
        widths = [0] * n_cols
        for row in rows:
            for idx in range(n_cols):
                cell = row[idx] if idx < len(row) else ''
                widths[idx] = max(widths[idx], len(cell))
        return [w + 2 for w in widths]

    @staticmethod
    def _format_row_with_widths(row: list[str], widths: list[int]) -> str:
        """Render one table row using column widths and a format template."""
        template = ''.join(f'{{:<{width}}}' for width in widths)
        padded = row + [''] * (len(widths) - len(row))
        return template.format(*padded).rstrip()

    def write_ga_rates_output(self) -> str:
        """Write GA_rates.out at convergence using full-history filtering."""
        if self.settings['postprocess']:
            output_file = f"{self.loc}/extrapolated_rates.out"
        else:
            output_file = f"{self.loc}/GA_rates.out"
        pres, temp = self._rate_conditions()
        pres_unit = str(self.settings.get('pres_unit', 'Torr'))
        eligible, total_scanned = self._eligible_models_for_rate_output()

        sop = self.f_mdl.sop
        pes_ids = list(sop.pes_ids)
        species_by_pes = {
            pes_id: list(sop.species_names_in_pes(pes_id))
            for pes_id in pes_ids
        }

        pairs_by_pes: dict[int, set[tuple[str, str]]] = {
            pes_id: set() for pes_id in pes_ids
        }
        for pes_id, from_name, to_name in sop.reaction_iterator():
            if pes_id in pairs_by_pes:
                pairs_by_pes[pes_id].add((from_name, to_name))

        with open(output_file, 'w', encoding='utf-8') as fobj:
            fobj.write('GA convergence rate statistics\n')
            fobj.write(
                'max_score filter: score < '
                f'{float(self.settings["max_score"]):.6g}\n'
            )
            fobj.write(
                'geometric stats use strictly positive rates only '
                '(k > 0)\n'
            )
            fobj.write(
                'single-sample geometric std convention: 1.0\n'
            )
            fobj.write(
                f'Found models: {len(eligible)} '
                f'out of {total_scanned}\n\n'
            )

            if len(eligible) == 0:
                fobj.write('No models satisfied score < max_score.\n')
                return output_file

            table_to_kin_ids: dict[str, set[int]] = defaultdict(set)
            for table_name, mdl_id, _ in eligible:
                table_to_kin_ids[table_name].add(int(mdl_id))

            query_map = {
                table: sorted(list(kin_ids))
                for table, kin_ids in table_to_kin_ids.items()
            }

            db_rows = self.kin_db.get_rates_for_models(
                table_to_kin_ids=query_map,
                pres=pres,
                temp=temp,
                pes_ids=pes_ids,
            )

            values: dict[tuple[int, float, float, str, str], list[float]] = {
                }
            for (
                table,
                kin_id,
                p,
                t,
                pes_id,
                from_name,
                to_name,
                kval,
            ) in db_rows:
                _ = table
                _ = kin_id
                key = (int(pes_id), float(p), float(t), from_name, to_name)
                if key not in values:
                    values[key] = []
                values[key].append(float(kval))

            stats: dict[
                tuple[int, float, float, str, str],
                tuple[float, float] | None,
            ] = {}
            for key, kvals in values.items():
                stats[key] = self.geometric_mean_and_std(kvals)

            for pes_id in pes_ids:
                species = species_by_pes.get(pes_id, [])
                fobj.write(f'=== PES {pes_id} ===\n')
                for p in pres:
                    for t in temp:
                        fobj.write(
                            f'P = {p:g} {pres_unit} | T = {t:g} K\n'
                        )

                        table_rows: list[list[str]] = []
                        table_rows.append(['from'] + list(species))
                        for from_name in species:
                            row: list[str] = [from_name]
                            for to_name in species:
                                if (
                                    from_name,
                                    to_name,
                                ) not in pairs_by_pes[pes_id]:
                                    row.append('N/A')
                                    continue
                                val = stats.get(
                                    (
                                        pes_id,
                                        float(p),
                                        float(t),
                                        from_name,
                                        to_name,
                                    )
                                )
                                row.append(self._format_geo_cell(val))

                            table_rows.append(row)

                        col_widths = self._column_widths(table_rows)
                        for row in table_rows:
                            fobj.write(
                                self._format_row_with_widths(
                                    row=row,
                                    widths=col_widths,
                                ) + '\n'
                            )
                        fobj.write('\n')

        return output_file

    def run_sensitivity(self,
                        gen_id: int) -> None:
        if self.new_gen_has_been_created is False:
            restart = True
        else:
            restart = False
        if str(gen_id) in self.settings["SA_restart"]:
            selected = self.settings["SA_restart"][str(gen_id)]
        else:
            self.klog.info('On-the-fly sensitivity analysis.')
            sensitivity = Linear(
                models=self.goat,
                settings=self.settings,
                rc_tpls=self.input_tpls,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                restart=restart)
            sensitivity.run()
            selected = sensitivity.selected
        new_params = [
            p for p in selected
            if p not in self.settings['active_p']
                        ]
        new_p: bool = len(new_params) > 0
        for p in new_params:
            self.settings['active_p'].append(p)
        if new_p:
            self.sf.set_active_p(self.settings['active_p'])
            msg = 'Perturbing the following new parameters:\n'
            msg += "{}".format(new_params).replace("'", '"')
            self.klog.info(msg)

    def update_goat(self,
                    new_mdls: list[Model]) -> None:
        # Delegate selection and persistence to the GOATs manager. The
        # GOATs instance will keep a global pool of seen models and
        # return the chosen goat list for this generation.
        chosen: List[Model] = self.goats.update_with_generation(
            models=new_mdls,
            goat_length=self.settings['goat_length']
        )

        # Update local goat list and log stats
        self.goat = chosen
        if self.goat:
            goat_avrg = float(np.average([mdl.score for mdl in self.goat]))
        else:
            goat_avrg = float('nan')
        self.klog.info(f'GOAT AVERAGE SCORE: {goat_avrg:>60.2f}')

    def get_stats(
        self,
        models: list[Model],
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Calculate the standard deviation of each key in the
        parameters_names dictionary across all SOP objects.

        Returns:
            Dict[str, float]: Dictionary with the mean values for each key.
            Dict[str, float]:
                Dictionary with the standard deviation for each key.
        """

        sop_list: list[SOP] = [
            mdl.sop for mdl in models
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
                if key not in self.settings['active_p']:
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
    def create_next_gen(self,
                        gen: Generation
                        ) -> tuple[dict[int, Model], list[Model]]:
        """Return the list of models of the next generation.
        Important: reset the Modmdl.__id before creating
        the models.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Model]: Models for the next generation
        """
        pass
