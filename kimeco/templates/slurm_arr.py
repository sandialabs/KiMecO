slurmarrtpl = """#! /bin/bash -f

#SBATCH -N 1
#SBATCH --array=0-{n_exp}
#SBATCH --cpus-per-task {nprocs}
#SBATCH -q medium
#SBATCH --exclude={exclude_nodes}
#SBATCH -o logs/{filename}_%a.stdout
#SBATCH -e logs/{filename}_%a.err

#SBATCH -p {sub_queue}
#SBATCH --mem={mem_mb}

export OMP_NUM_THREADS={nprocs}
echo $SLURM_JOB_NODELIST

# Create the scratch directory
SCRATCHDIR={scratchdir}
mkdir -p $SCRATCHDIR

"""