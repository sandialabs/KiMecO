#! /bin/bash -f
  
#SBATCH -N 1
#SBATCH --ntasks=1  
#SBATCH -q medium
#SBATCH -o input.stdout
#SBATCH -e input.err

#SBATCH -p week-long-cpu
#SBATCH --mem=500
export OMP_NUM_THREADS=1

echo $SLURM_JOB_NODELIST
/usr/bin/time -v kmo input.json
