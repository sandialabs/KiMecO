sim_helper = """
import json
import numpy as np
from kimeco.database.sim_db import SIM_DB
import sqlalchemy
import time
import os

hid = {hlp_idx}

db = SIM_DB(name='{db.name}',
             path='{db.path}',
             tbl_name='{table}')

filenames = {filenames}

collected = np.full(len(filenames), False)
sims = [None for i in range(len(filenames))]

while not all(collected):
    for idx, fn in enumerate(filenames):
        if os.path.isfile(fn):
            # Happens if the file is being written
            while True:
                if os.path.getsize(fn) == 0:
                    time.sleep(0.2)
                else:
                    break
            with open(fn, 'r') as f:
                sim = json.load(f)
            sims[idx] = sim
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
        db.prepare_batch_upsert(table='{table}',
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
        wait_time = upsert_start - now
        db.batch_upsert()
        upsert_stop = time.time()
        upsert_time = upsert_stop - upsert_start
        print(f'Helper waited {{wait_time}} s to start writting.')
        print(f'Helper wrote {{len(filenames)}} profiles in the db in {{upsert_time}} s.')
        break
    # Happens when db is occupied/locked
    except sqlalchemy.exc.OperationalError as e:
        print(e)
        time.sleep(5)
# Only clean JSON file after data are saved
for idx, fn in enumerate(filenames):
    os.remove(fn)

            """
