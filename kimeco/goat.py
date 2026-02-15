from typing import List, Tuple, Union, Optional, Dict
import numpy as np
from numpy.typing import NDArray
from typing import Any


from kimeco.element import Element
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB


Pair = Tuple[float, float]
SpeciesPair = Tuple[str, str]
ElemKey = Tuple[int, int]
PerElem = Dict[ElemKey, Optional[float]]
PerPair = Dict[SpeciesPair, PerElem]
PerCond = Dict[Pair, PerPair]
RateResult = Dict[int, PerCond]


class GOATs:
    """
    Represents GOAT states loaded from a file.
    Each file line corresponds to a generation (line 0 -> generation 0).
    Each line is a series of tokens separated by spaces. Each token is "x_y"
    where x and y are integers. Parsed as tuples (x, y).
    """

    def __init__(self,
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 wdir: str = '.',
                 overwrite: bool = True,
                 prefix: str = 'G') -> None:
        """Load GOATs from a file and keep references to databases.

        Args:
            filename: path to goat file
            sop_db: SOP_DB instance used to reconstruct SOP objects
            kin_db: KIN_DB instance (kept for API symmetry)
            sim_db: SIM_DB instance (kept for API symmetry)
        """
        # Don't read any file in the default constructor: the GA creates
        # GOATs in-memory and will set filename when appropriate. Use
        # `from_file()` to construct an instance from an existing file.
        self.filename: str = 'goats.txt'
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.wdir: str = wdir
        self.prefix: str = prefix

        # generations is a list where each index corresponds to a
        # generation number and stores a list of (gen_id, el_id) tuples
        # representing the GOAT elements for that generation.
        self.generations: List[List[Tuple[int, int]]] = []
        self.scores: list[list[float]] = []

        # all_seen stores Element objects we've been given through
        # update_with_generation so we can compute the global bests.
        # Keyed by (gen, id) -> Element
        self.all_seen: Dict[Tuple[int, int], Element] = {}

        self.score_line_tpl = '{iter:>10}{best_score:>15}{score_avrg:>15}\n'
        if overwrite:
            with open(self.wdir + '/score_info.txt', 'w') as f:
                f.write(self.score_line_tpl.format(
                        iter='ITER',
                        best_score='BEST SCORE',
                        score_avrg='GOAT AVERAGE'))

    @classmethod
    def from_file(cls,
                  filename: str,
                  sop_db: SOP_DB,
                  kin_db: KIN_DB,
                  sim_db: SIM_DB) -> "GOATs":
        """Create a GOATs instance loaded from a goat file.

        This classmethod reads the file and returns a GOATs instance whose
        `generations` are populated. It does not populate `all_seen` (that
        is built dynamically by update_with_generation).
        """
        inst = cls(
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            overwrite=False)
        inst.filename = filename
        gens: List[List[Tuple[int, int]]] = []
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                for lineno, raw in enumerate(fh):
                    goat_list: List[str] = raw.strip().split()
                    if not goat_list:
                        continue
                    goats: List[Tuple[int, int]] = []
                    for el in goat_list:
                        try:
                            a, b = el.split("_", 1)
                            goats.append((int(a), int(b)))
                        except Exception as exc:
                            raise ValueError(
                                (
                                    f"Malformed element on line {lineno+1}: '")
                                + f"{el}'"
                            ) from exc
                    gens.append(goats)
        except FileNotFoundError:
            raise FileNotFoundError(f"GOAT file '{filename}' not found")
        except Exception as exc:
            raise RuntimeError(f"Failed to read GOAT file '{filename}': {exc}")
        inst.generations = gens
        return inst

    def get_goat_for_gen(self, generation_number: int) -> List[Element]:
        """Return a list of Element objects for the given generation number.

        The GOAT file stores tokens as "genId_elId" (e.g. "0_12"). Each
        token corresponds to an element stored in the corresponding
        generation table in the SOP DB. This method queries the SOP_DB to
        reconstruct SOP objects (using SOP_DB.sop_tpl as template and
        SOP.from_db_row) and returns Element instances with proper ids and
        generation set.
        """
        if generation_number == -1:
            generation_number = len(self.generations) - 1
        if generation_number < 0 or generation_number >= len(self.generations):
            raise IndexError("Generation number out of range")

        elements: List[Element] = []
        # Each entry in self.generations[generation_number] is a tuple
        # (gen_id, el_id)
        gen_ids = []
        el_ids = []
        tables = {}

        for gen_id, el_id in self.generations[generation_number]:
            # Table name in DBs follows the pattern G{gen_id:04d}
            table: str = f"{self.prefix}{gen_id:04d}"
            if table not in tables:
                tables[table] = []
            tables[table].append(el_id)
            gen_ids.append(gen_id)
            el_ids.append(el_id)

        # Prepare batch select for all required SOP rows
        for table, ids in tables.items():
            for el_id in ids:
                self.sop_db.prepare_batch_select(table=table, row_id=el_id)

        # Execute batch select
        try:
            rows: Dict[int, List[List[Any]]] = \
                self.sop_db.batch_select_to_dict()
        except Exception as exc:
            raise RuntimeError(f"Failed to retrieve SOP rows: {exc}") from exc

        # Map rows to Elements
        for gen_id, el_id in zip(gen_ids, el_ids):
            # drop the id column and reconstruct SOP
            table = np.array(rows[f'{self.prefix}{gen_id:04d}'])
            row: str = table[table[:, 0] == el_id][:,1:]
            if len(row) != 1:
                msg = "Expected exactly one row for id "
                msg += f"{el_id} in table G{gen_id:04d}, found {len(row)}"
                raise ValueError(msg)
            sop_obj = self.sop_db.sop_tpl.__class__.from_db_row(
                sop_tpl=self.sop_db.sop_tpl,
                row=row[0]
            )
            el = Element(sop=sop_obj, id=el_id, gen=gen_id)
            elements.append(el)

        return elements

    def update_with_generation(self,
                               elements: List[Element],
                               goat_length: int) -> List[Element]:
        """Update internal GOATs state with a newly computed generation.

        This method records the provided Element objects in the internal
        'all_seen' pool, computes the best `goat_length` elements across all
        seen elements (lower score is better), stores the resulting tokens as
        the GOAT for that generation index, and writes the whole GOAT file.

        Returns the list of selected Element objects.
        """
        if not elements:
            raise ValueError(
                "No elements provided for update_with_generation")

        gen_id: int = max(el.gen for el in elements)

        # Add new elements to pool
        for el in elements:
            self.all_seen[(el.gen, el.id)] = el

        # Build candidate list from all seen elements up to this gen
        candidates: List[Element] = [
            el
            for (g, _), el in self.all_seen.items()
            if g <= gen_id
        ]

        # Sort ascending by score (lower is better) and pick top N
        chosen: List[Element] = sorted(
            candidates, key=lambda e: e.score)[:goat_length]

        # Ensure self.generations is long enough
        if len(self.generations) <= gen_id:
            # pad with empty lists
            self.generations.extend(
                [[] for _ in range(gen_id - len(self.generations) + 1)]
            )

        # Store tokens for this generation
        self.generations[gen_id] = [(el.gen, el.id) for el in chosen]

        # Persist full file (rewrite) to keep it consistent
        with open(self.wdir + '/' + self.filename, 'w', encoding='utf-8') as f:
            for goats in self.generations:
                if not goats:
                    f.write('\n')
                    continue
                line = ' '.join(f"{g}_{i}" for g, i in goats)
                f.write(line + '\n')

        best_score: float = min(el.score for el in chosen)
        average_score = np.average([el.score for el in chosen])
        with open(self.wdir + '/score_info.txt', 'a', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter=f"{gen_id:04d}",
                best_score=f"{best_score:.3f}",
                score_avrg=f"{average_score:.3f}"))
        return chosen

    def get_rate_coefficients(
        self,
        req_conditions: List[Tuple[float, float]],
        gen_ids: List[int],
        from_to: tuple[str, str],
    ) -> RateResult:
        """Return rate coefficients for GOAT elements in the requested
        generations and conditions.

        This method minimizes DB queries by batching requests using
        KIN_DB.prepare_batch_select(...) and a single call to
        KIN_DB.batch_select().

        Args:
            req_conditions: list of (pressure, temperature) tuples
            gen_ids: list of generation indices to query (indexes in
                     self.generations)
            rate_pairs: list of (From, To) species name tuples

        Returns:
            Nested dict structured per generation, per (p,t) condition and
            per (From,To) pair mapping element keys to floats or None.

        Notes:
            - A generation may contain multiple GOAT elements; the return
              maps each (el.gen, el.id) to the corresponding rate value.
            - Missing DB entries are represented as None.
        """
        # Clear any previous selects in kin_db and prepare batched selects
        # NOTE: KIN_DB.prepare_batch_select appends into kin_db._select
        # so we just call it repeatedly and then a single batch_select().

        # Collect element tokens (gen,id) per requested generation.
        # We avoid reconstructing Element objects here and use the
        # stored tokens directly to minimize work.
        # gen_elements: Dict[int, List[Tuple[int, int]]] = {}
        # for gen_id in gen_ids:
        #     tokens = self.generations[gen_id]
        #     gen_elements[gen_id] = tokens

        # Prepare batch selects for every element token / condition /
        # rate_pair. gen_elements stores tuples (elem_gen, elem_id).
        for gen_id in gen_ids:
            for (elem_gen, elem_id) in self.generations[gen_id]:
                table: str = f"{self.prefix}{elem_gen:04d}"
                kin_id = int(elem_id)
                for (p, t) in req_conditions:
                    # KIN_DB expects From, To parameter names
                    self.kin_db.prepare_batch_select(
                        table=table,
                        kin_id=kin_id,
                        p=float(p),
                        t=float(t),
                        From=from_to[0],
                        To=from_to[1])

        raw_results = self.kin_db.batch_select()

        # Assemble results in requested shape
        out: dict[int, dict[tuple[float, float], list[float]]] = {}
        for gen_id in gen_ids:
            out[gen_id] = {}
            for (p, t) in req_conditions:
                key = (p, t, from_to[1], from_to[0])
                out[gen_id][(p, t)] = []
                for (elem_gen, elem_id) in self.generations[gen_id]:
                    table = f"{self.prefix}{elem_gen:04d}"
                    kin_id = int(elem_id)
                    out[gen_id][(p, t)].append(
                        float(raw_results[table][kin_id][key]))
        return out

    def get_p_for_gen(self,
                      params: List[str],
                      gen_id: int) -> NDArray:
        """Return requested SOP parameters for GOAT elements.

        Args:
            params: list of parameter names (keys in SOP.parameters_names)
            gen_ids: list of generation indices to query

        Returns:
            dict mapping gen_id -> { param_name: np.array(values) }

        """

        for (gen_origin, el_id) in self.generations[gen_id]:
            table: str = f"{self.prefix}{gen_origin:04d}"
            self.sop_db.prepare_batch_select(table=table, row_id=el_id)

        # Execute batched select once
        raw_cols: List[Tuple[Any]] = self.sop_db.batch_select_cols(cols=params)

        return np.array(raw_cols)

    def __len__(self) -> int:
        return len(self.generations)

    def __getitem__(self, idx: Union[int, slice]) -> \
            Union[List[Tuple[int, int]], List[List[Tuple[int, int]]]]:
        return self.generations[idx]

    def generation(self, n: int) -> List[Tuple[int, int]]:
        """Return list of (x, y) tuples for generation n."""
        return self.generations[n]

    def latest(self) -> List[Tuple[int, int]]:
        """Return the last (most recent) generation."""
        if not self.generations:
            return []
        return self.generations[-1]

    def __repr__(self) -> str:
        return f"GOATs(filename={self.filename!r}, generations={len(self)})"

