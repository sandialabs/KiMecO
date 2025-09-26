pyarrtpl = """
FORMATTED_ID=$(printf "%02d" $SLURM_ARRAY_TASK_ID)
python {filename}.py $SLURM_ARRAY_TASK_ID

mv {scratchdir}/{filename}${{FORMATTED_ID}}.json {destination}
"""