pyarrtpl = (
    "FORMATTED_ID=$(printf \"%02d\" $SLURM_ARRAY_TASK_ID)\n"
    "PY_FILES=({filenames})\n"
    "PY_FILE=${{PY_FILES[$SLURM_ARRAY_TASK_ID]}}\n"
    "python \"$PY_FILE\" $SLURM_ARRAY_TASK_ID\n\n"
    "mv {scratchdir}/{filename}${{FORMATTED_ID}}.json {destination}\n"
)

# End of file
