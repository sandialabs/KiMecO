sim_helper = """
import json
import numpy as np
from game.database.sim_db import SIM_DB
import sqlalchemy
import time
import os

hid = {hlp_idx}

db = SIM_DB(name='{db.name}',
             path='{db.path}')

filenames = {filenames}

collected = np.full(len(filenames), False)
sims = []

while not all(collected):
    for idx, fn in enumerate(filenames):
        if os.path.isfile(fn):
            with open(fn, 'r') as f:
                sim = json.load(f)
            sims.append(sim)
            os.remove(fn)
            collected[idx] = True
        # Helpers should not try to collect data from failed sims.
        else:
            raise FileNotFoundError(f'Could not find data for {{fn}}.')

for sim in sims:
    row_ids = sim['row_ids']
    sim.pop('row_ids', None)
    for idx, id in enumerate(row_ids):
        row_dict = {{}}
        for col in sim:
            row_dict[col] = sim[col][idx]
        db.prepare_batch_upsert(table='G{gen}',
                                id=id,
                                values=row_dict)
trying2connect = True

# Stop trying after 3 minutes
start = time.time()
while trying2connect:
    now = time.time()
    if now-start > 180:
        raise ValueError(
            'Could not access the database for more than 2 minutes.'
        )
    try:
        upsert_start = time.time()
        db.batch_upsert()
        upsert_stop = time.time()
        upsert_time = upsert_stop - upsert_start
        print(f'Writting {{len(filenames)}} profiles in the db took {{upsert_time}} secondes.')
        break
    # Happens when db is occupied/locked
    except sqlalchemy.exc.OperationalError:
        time.sleep(5)
            """