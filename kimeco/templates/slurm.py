slurmtpl = """#! /bin/bash -f

#SBATCH -N 1
#SBATCH -c {nprocs}
#SBATCH -q medium
#SBATCH --exclude={exclude_nodes}
#SBATCH -o logs/{filename}.stdout
#SBATCH -e logs/{filename}.err

#SBATCH -p {sub_queue}
#SBATCH --mem={mem_mb}

export OMP_NUM_THREADS={nprocs}
echo $SLURM_JOB_NODELIST"""