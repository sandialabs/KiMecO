#! /bin/bash -f
  
#SBATCH -N 1
#SBATCH --ntasks=1                   # Number of tasks (usually 1 for multi-threaded jobs)
#SBATCH -q medium
#SBATCH -o logs/input.stdout
#SBATCH -e logs/input.err

#SBATCH -p week-long-cpu
#SBATCH --mem=1000
export OMP_NUM_THREADS=1

source ~/.bashrc
conda activate game

echo $SLURM_JOB_NODELIST
/usr/bin/time -v kmo input.json
