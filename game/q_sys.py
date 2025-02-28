from game.templates.pyjob import pytpl
from game.templates.messjob import messtpl
from game.templates.slurm import slurmtpl
from subprocess import Popen, PIPE
import numpy as np
from numpy.typing import NDArray
from numpy import int16, int32, unicode_
from typing import Any
import getpass
import os


class QueueingSystem:
    def __init__(self,
                 max_jobs: int,
                 max_cpu: int,
                 max_mem: int,
                 nkin: int,
                 nsim: int,
                 nhlp: int,
                 cpu_kin: int,
                 cpu_sim: int,
                 mem_kin: int,
                 mem_sim: int,
                 q_type: str = 'slurm',
                 q_name: str = 'day-long-cpu'
                 ) -> None:
        """The queueing system is only meant to manage the number of jobs
        and the ressources used by the workflow. The run() method should
        only submit jobs to use a maximum of ressources. But it should not:
        - Do science
        - Write files

        File writting should be done by other instances of GAME, which will be
        visited when the ressources are fully used
        or when the work queue is empty.

        Args:
            max_jobs (int): Max number of jobs to be used by the WF.
            max_cpu (int): Max number of cpu to be used by the WF
            max_mem (int): Max quantity of memory (Mb) to be used by the WF
            cpu_job (int, optional): Number of cpu used for each job.
                                     Defaults to 1.
            mem_kin (float, optional): Quantity of memory (Mb) used
                                       for each kin job. Defaults to 500.0.
            mem_sim (float, optional): Quantity of memory (Mb) used
                                       for each sim job. Defaults to 500.0.
            location (str, optional): Where jobs should be submitted from.
                                      Defaults to local.
        """

        self.av_jobs: int = max_jobs
        self.av_cpu: int = max_cpu
        self.av_mem: int = max_mem
        self.cpu_kin: int = cpu_kin
        self.cpu_sim: int = cpu_sim
        self.mem_kin: int = mem_kin
        self.mem_sim: int = mem_sim
        if q_type.casefold() == 'slurm':
            self.subtpl: str = slurmtpl
            self.ext: str = 'slurm'
        else:
            raise NotImplementedError('Slurm is the only q_type available.')
        self.pytpl: str = pytpl
        self.messtpl: str = messtpl
        self.q_name: str = q_name
        # define a dtype object to create a structured numpy array.
        self.jobdata = np.dtype(dtype=[
            ('sub_id', int32),
            ('name', unicode_, (20)),
            ('loc', unicode_, (150)),
            ('status', unicode_, (10)),
            ('cpu', int16),
            ('mem', int32),
            ('type', unicode_, (3))])

        self.kin_q: NDArray[Any] = np.empty(shape=(nkin),
                                            dtype=self.jobdata)

        self.sim_q: NDArray[Any] = np.empty(shape=(nsim),
                                            dtype=self.jobdata)

        self.hlp_q: NDArray[Any] = np.empty(shape=(nhlp),
                                            dtype=self.jobdata)
        self.submitted: int = 0
        self.running: int = 0
        self.n_ready: int = 0

    def add_to_q(self,
                 name: str,
                 idx: int,
                 location: str,
                 jtype: str,
                 ressources: tuple[int, int]
                 ) -> None:
        """Create the submission file when job is added to queue.
           Job file itself must have already been created by the submitting
           instance.

        Args:
            location (str): Absolute path to the folder
            name (str): filename without extension
            idx (int): position in the queue of type jtype
            jtype (str): <kin> (for kinetic) or <sim> (simulation)
            ressources (tuple[int, int]): number of CPU and memory (Mb)
        """
        cpu: int
        mem: int  # In Mb
        (cpu, mem) = ressources
        job: NDArray[Any] = np.array([
            (0,
             name,
             location,
             'ready',
             cpu,
             mem,
             jtype)], dtype=self.jobdata)
        self.create_sub_file(job=job)
        if jtype == 'kin':
            self.kin_q[idx] = job[0]
        elif jtype == 'sim':
            self.sim_q[idx] = job[0]
        elif jtype == 'hlp':
            self.sim_q[idx] = job[0]
        self.n_ready += 1

    def create_sub_file(self,
                        job: NDArray[Any]
                        ) -> None:
        """Create the submission script for the job.

        Args:
            job (Job): Numpy structured array. dtype = jobdata
        """
        sub_cmd: str = self.subtpl.format(nprocs=job['cpu'][0],
                                          filename=str(job['name'][0]),
                                          sub_queue=self.q_name,
                                          mem_mb=job['mem'][0]
                                          )
        # Mess jobs
        if job['type'] == 'kin':
            job_cmd: str = self.messtpl.format(filename=str(job['name'][0]))
        # Python jobs
        elif job['type'] == 'sim' or job['type'] == 'hlp':
            job_cmd: str = self.pytpl.format(filename=str(job['name'][0]))

        sub_file: str = sub_cmd + job_cmd

        with open(f"{job['loc'][0]}/{job['name'][0]}.{self.ext}", 'w') as f:
            f.write(sub_file)

    def pickUp(self,
               id: int,
               jtype: str) -> None:
        """Tag a job as ready to be removed from the queue.

        Args:
            id (str): id of the job.
        """
        job: NDArray[Any]
        if jtype == 'kin':
            job = self.kin_q[id]
        elif jtype == 'sim':
            job = self.sim_q[id]
        elif jtype == 'hlp':
            job = self.sim_q[id]

        clear_err = True

        if (jtype == 'kin' and os.path.exists(
           path=f"{job['loc']}/{job['name']}.out"
           )) or (jtype == 'sim'):
            # If the error file is not empty, a problem occured.
            # Could be convergence of ME -> Reset the job
            if not os.path.exists(
               path=f"{job['loc']}/{job['name']}.err"
               ) or os.stat(
               path=f"{job['loc']}/{job['name']}.err"
               ).st_size == 0:
                job['status'] = 'pickedUp'
            else:
                job['status'] = 'fail'
                clear_err = False
                print(f"Resetting job {job['name']} because an error occured.")
                if os.path.exists(f"{job['loc']}/{job['name']}.out"):
                    os.remove(f"{job['loc']}/{job['name']}.out")
        elif jtype == 'hlp':
            if os.path.exists(
               path=f"{job['loc']}/{job['name']}.err"
               ) and os.stat(
               path=f"{job['loc']}/{job['name']}.err"
               ).st_size != 0:
                clear_err = False
                print(f"Helper {job['name']} failed.")
                job['status'] = 'fail'
        self.clean_files(job,
                         clear_err=clear_err)
        # self.av_cpu += int(job['cpu'])
        # self.av_mem += int(job['mem'])
        # self.av_jobs += 1

    def clean_files(self,
                    job: NDArray[Any],
                    clear_err: bool) -> None:
        """Erase all files except the output
        if the job finished without error.

        Args:
            job (NDArray[Any]): Array of the job with custom datatype.
        """
        for ext in ['log', 'err', 'inp', 'stdout', 'aux', 'slurm', 'pkl']:
            if ext == 'err' and not clear_err:
                continue
            if os.path.exists(f"{job['loc']}/{job['name']}.{ext}"):
                os.remove(f"{job['loc']}/{job['name']}.{ext}")

    def submit(self,
               job) -> None:
        """Go in the submission directory,
        submit the job, and return the slurm's job id.
        Set the Job's status to <running>.

        Args:
            job: Numpy structured array. dtype = jobdata

        """

        command: list[str] = ['sbatch', str(job['name']) + '.' + self.ext]
        process = Popen(args=command,
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        outstr: str = out.decode()
        slurm_id: int = int(outstr.split()[-1])
        job['sub_id'] = np.int32(slurm_id)
        job['status'] = 'running'
        self.av_cpu -= job['cpu']
        self.av_mem -= job['mem']
        self.av_jobs -= 1
        self.n_ready -= 1

    def run(self) -> None:
        """Run all jobs of the workflow in parallel
        as long as ressources are available.
        """
        for job in self.kin_q:
            if job['status'] == 'ready':
                if self.enough_ressources_for(job):
                    self.submit(job=job)
                else:
                    self.actualize()
                    break
        for job in self.sim_q:
            if job['status'] == 'ready':
                if self.enough_ressources_for(job):
                    self.submit(job=job)
                else:
                    self.actualize()
                    break
        if self.n_ready < self.av_jobs:
            self.actualize()

    def enough_ressources_for(self,
                              job) -> bool:
        """Check remaining ressources are enough
        to send the job.

        Args:
            job (_type_): Numpy structured array. dtype = jobdata

        Returns:
            bool: True is enough ressources.
        """
        if self.av_jobs > 0 \
           and self.av_cpu > job['cpu']\
           and self.av_mem > job['mem']:
            return True
        else:
            return False

    def actualize(self) -> None:
        """Remove picked up jobs from queuing system.
        Change status of newly finished jobs.
        """
        slurm_ids: NDArray[int32] = self.get_all_running()
        for job in self.kin_q:
            if job['status'] == 'ready' or\
               job['status'] == 'fail':
                continue
            elif job['status'] == 'running' \
               and not any(slurm_ids == job['sub_id']):
                job['status'] = 'finished'
                self.av_cpu += job['cpu']
                self.av_mem += job['mem']
                self.av_jobs += 1
        for job in self.sim_q:
            if job['status'] == 'ready':
                continue
            elif job['status'] == 'running' \
               and not any(slurm_ids == job['sub_id']):
                job['status'] = 'finished'
                self.av_cpu += job['cpu']
                self.av_mem += job['mem']
                self.av_jobs += 1

    def get_all_running(self) -> NDArray[int32]:
        """Create numpy array of job ids for fast comparaison
        with job ids in running list

        Returns:
            NDArray[int32]: job ids in return of command squeue -u user
        """
        process = Popen(args=['squeue', '-u', f'{getpass.getuser()}'],
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        jobs: list[str] = out.decode().split('\n')[1:]
        slurm_ids: NDArray[int32] = np.zeros(len(jobs), dtype=np.int32)
        for i, j in enumerate(jobs[:-1]):
            slurm_ids[i] = int32(j.split()[0])
        return slurm_ids

    def status(self,
               id: int,
               jtype) -> str:
        if jtype == 'kin':
            # Any checks if the array has a content.
            # Return false if empty.
            if self.kin_q[id]['status'] != '':
                return self.kin_q[id]['status']
            else:
                return 'notInQueue'
        else:  # jtype == 'sim':
            if self.sim_q[id]['status'] != '':
                return self.sim_q[id]['status']
            else:
                return 'notInQueue'
