pyarrtpl = (
    "FORMATTED_ID=$(printf \"%02d\" $SLURM_ARRAY_TASK_ID)\n"
    "python {filename}_${FORMATTED_ID}.py $SLURM_ARRAY_TASK_ID\n\n"
    "mv {scratchdir}/{filename}${FORMATTED_ID}.json {destination}\n"
)

# End of file
