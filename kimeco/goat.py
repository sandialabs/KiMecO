from typing import List, Tuple, Union

# /home/csoulie/GAME/kimeco/goat.py


from kimeco.element import Element
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB


class GOATs:
    """
    Represents GOAT states loaded from a file.
    Each file line corresponds to a generation (line 0 -> generation 0).
    Each line is a series of tokens separated by spaces. Each token is "x_y"
    where x and y are integers. Parsed as tuples (x, y).
    """

    def __init__(self,
                 filename: str,
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB) -> None:
        """Load GOATs from a file and keep references to databases.

        Args:
            filename: path to goat file
            sop_db: SOP_DB instance used to reconstruct SOP objects
            kin_db: KIN_DB instance (kept for API symmetry)
            sim_db: SIM_DB instance (kept for API symmetry)
        """
        self.filename = filename
        self.sop_db = sop_db
        self.kin_db = kin_db
        self.sim_db = sim_db
        self.generations: List[List[Tuple[int, int]]] = []
        with open(self.filename, "r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh):
                line = raw.strip()
                if not line:
                    # empty generation: no goats
                    self.generations.append([])
                    continue
                parts = line.split()
                goats: List[Tuple[int, int]] = []
                for token in parts:
                    try:
                        a, b = token.split("_", 1)
                        goats.append((int(a), int(b)))
                    except Exception as exc:
                        raise ValueError(
                            f"Malformed token on line {lineno+1}: '{token}'"
                        ) from exc
                self.generations.append(goats)

    def get_goat_for_gen(self, generation_number: int) -> List[Element]:
        """Return a list of Element objects for the given generation number.

        The GOAT file stores tokens as "genId_elId" (e.g. "0_12"). Each
        token corresponds to an element stored in the corresponding
        generation table in the SOP DB. This method queries the SOP_DB to
        reconstruct SOP objects (using SOP_DB.sop_tpl as template and
        SOP.from_db_row) and returns Element instances with proper ids and
        generation set.
        """
        if generation_number < 0 or generation_number >= len(self.generations):
            raise IndexError("Generation number out of range")

        elements: List[Element] = []
        # Each entry in self.generations[generation_number] is a tuple
        # (gen_id, el_id)
        for gen_id, el_id in self.generations[generation_number]:
            # Table name in DBs follows the pattern G{gen_id:04d}
            table = f"G{gen_id:04d}"
            try:
                # get_sop_row returns full row including id as first column
                row = self.sop_db.get_sop_row(table=table, id=el_id)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to retrieve SOP row for {table} id {el_id}: {exc}"
                ) from exc

            # drop the id column and reconstruct SOP
            # get_sop_row returns a list-like Row where the first entry is id
            sop_vals = list(row)[1:]
            sop_obj = self.sop_db.sop_tpl.__class__.from_db_row(
                sop_tpl=self.sop_db.sop_tpl,
                row=sop_vals
            )
            el = Element(sop=sop_obj, id=el_id, gen=gen_id)
            elements.append(el)

        return elements

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

