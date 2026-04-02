kin_arr_tpl = """
FORMATTED_ID=$(printf "%02d" $SLURM_ARRAY_TASK_ID)
mess {filename}P${{FORMATTED_ID}}.inp
"""
