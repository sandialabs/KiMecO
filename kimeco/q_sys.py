from enum import Enum
from kimeco.templates.pyjob import pytpl
from kimeco.templates.messjob import messtpl
from kimeco.templates.slurm import slurmtpl
from subprocess import Popen, PIPE
import numpy as np
from numpy.typing import NDArray
from numpy import int16, int32, ndarray, str_
from typing import Any
import getpass
import os
import logging
from kimeco.logger_config import setup_logger
import time


setup_logger()
glog = logging.getLogger()


class JobStatus(Enum):
    READY = 'ready'
    RUNNING = 'running'
    FINISHED = 'finished'
    PICKED_UP = 'pickedUp'
    FAILED = 'fail'
    NOT_IN_QUEUE = 'notInQueue'


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
                 q_name: str = 'day-long-cpu') -> None:
        """The queueing system is only meant to manage the number of jobs
        and the ressources used by the workflow. The run() method should
        only submit jobs to use a maximum of ressources. But it should not:
        - Do science
        - Write files

        File writting should be done by other instances of KIMECO, which will be
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
        self._max_jobs: int = max_jobs
        self._max_cpu: int = max_cpu
        self._max_mem: int = max_mem
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

        # Define a dtype object to create a structured numpy array.
        self.jobdata = np.dtype(dtype=[
            ('sub_id', int32),
            ('name', str_, (20)),
            ('loc', str_, (150)),
            ('status', str_, (10)),
            ('cpu', int16),
            ('mem', int32),
            ('type', str_, (3))])

        self.kin_q: NDArray[Any] = np.empty(shape=(nkin), dtype=self.jobdata)
        self.sim_q: NDArray[Any] = np.empty(shape=(nsim), dtype=self.jobdata)
        self.hlp_q: NDArray[Any] = np.empty(shape=(nhlp), dtype=self.jobdata)
        self.queues: list[NDArray] = [self.kin_q, self.sim_q, self.hlp_q]

        self.submitted: int = 0
        self.running: int = 0

    @property
    def av_jobs(self):
        job_sum = len(self.kin_q[self.kin_q['status'] == JobStatus.RUNNING])
        job_sum += len(self.sim_q[self.sim_q['status'] == JobStatus.RUNNING])
        job_sum += len(self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING])
        return self._max_jobs - job_sum

    @property
    def av_cpu(self):
        cpu_sum = np.sum(
            self.kin_q[self.kin_q['status'] == JobStatus.RUNNING]['cpu'])
        cpu_sum += np.sum(
            self.sim_q[self.sim_q['status'] == JobStatus.RUNNING]['cpu'])
        cpu_sum += np.sum(
            self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING]['cpu'])
        return self._max_cpu - cpu_sum

    @property
    def av_mem(self):
        mem_sum = np.sum(
            self.kin_q[self.kin_q['status'] == JobStatus.RUNNING]['mem'])
        mem_sum += np.sum(
            self.sim_q[self.sim_q['status'] == JobStatus.RUNNING]['mem'])
        mem_sum += np.sum(
            self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING]['mem'])
        return self._max_mem - mem_sum

    @property
    def n_ready(self):
        n_ready = len(self.kin_q[self.kin_q['status'] == JobStatus.READY])
        n_ready += len(self.sim_q[self.sim_q['status'] == JobStatus.READY])
        n_ready += len(self.hlp_q[self.hlp_q['status'] == JobStatus.READY])
        return n_ready

    def add_to_q(self,
                 name: str,
                 idx: int,
                 location: str,
                 jtype: str,
                 ressources: tuple[int, int]) -> None:
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
        cpu, mem = ressources
        job: NDArray[Any] = np.array([
            (0, name, location, JobStatus.READY.value, cpu, mem, jtype)],
            dtype=self.jobdata)
        self.create_sub_file(job=job)

        if jtype == 'kin':
            self.kin_q[idx] = job[0]
        elif jtype == 'sim':
            self.sim_q[idx] = job[0]
        elif jtype == 'hlp':
            self.hlp_q[idx] = job[0]

    def create_sub_file(self,
                        job: NDArray[Any]) -> None:
        """Create the submission script for the job."""
        sub_cmd: str = self.subtpl.format(
            nprocs=job['cpu'][0],
            filename=str(job['name'][0]),
            sub_queue=self.q_name,
            mem_mb=job['mem'][0]
        )
        job_cmd: str

        if job['type'] == 'kin':
            job_cmd = self.messtpl.format(filename=str(job['name'][0]))
        elif job['type'] in ['sim', 'hlp']:
            job_cmd = self.pytpl.format(filename=str(job['name'][0]))

        sub_file: str = sub_cmd + job_cmd

        with open(f"{job['loc'][0]}/{job['name'][0]}.{self.ext}", 'w') as f:
            f.write(sub_file)

    def pickUp(self, id: int, jtype: str) -> None:
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
            job = self.hlp_q[id]

        clear_err = True
        file: str = f"{job['loc']}/{job['name']}"
        if (jtype == 'kin' and os.path.exists(f"{file}.out")) or\
           jtype == 'sim':
            while not (os.path.exists(f"{file}.err")):
                time.sleep(0.1)
            if os.stat(f"{file}.err").st_size > 0:
                job['status'] = JobStatus.FAILED.value
                clear_err = False
                glog.warning(
                    f"Resetting job {job['name']} because an error occurred.")
                if jtype == 'kin':
                    os.remove(f"{file}.out")
            else:
                job['status'] = JobStatus.PICKED_UP.value
        elif jtype == 'hlp':
            if (os.path.exists(f"{file}.err") and
                    os.stat(
                        f"{file}.err").st_size > 0):
                job['status'] = JobStatus.FAILED.value
                clear_err = False
                glog.info(f"Helper {job['name'][0]} failed.")
            else:
                job['status'] = JobStatus.PICKED_UP.value
        self.clean_files(job, clear_err=clear_err)

    def clean_files(self,
                    job: NDArray[Any],
                    clear_err: bool) -> None:
        """Erase all files except the output
        if the job finished without error.

        Args:
            job (NDArray[Any]): Array of the job with custom datatype.
        """
        # Don't delete files for jobs that need to be resubmitted
        if job['status'] == JobStatus.READY.value:
            return
        for ext in ['log', 'err', 'inp', 'stdout', 'aux', 'slurm', 'pkl']:
            if ext == 'err' and not clear_err:
                continue
            if os.path.exists(f"{job['loc']}/{job['name']}.{ext}"):
                os.remove(f"{job['loc']}/{job['name']}.{ext}")

    def submit(self, job) -> None:
        """Submit the job, and return the slurm's job id.
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
        if process.returncode != 0:
            msg = f"Failed to submit {job['name']}" +\
                f": {err.decode().strip()}"
            glog.error(msg)
            return  # Handle the error appropriately
        slurm_id: int = int(outstr.split()[-1])
        job['sub_id'] = np.int32(slurm_id)
        job['status'] = JobStatus.RUNNING.value

    def run(self) -> None:
        """Run all jobs of the workflow in parallel
        as long as ressources are available.
        """
        for q in self.queues:
            for idx, rdy in enumerate(q['status'] == JobStatus.READY.value):
                if rdy:
                    if self.enough_resources_for(job=q[idx]):
                        self.submit(job=q[idx])
                    else:
                        self.actualize()
                        break
        if self.n_ready <= self.av_jobs:
            self.actualize()

    def enough_resources_for(self, job) -> bool:
        """Check if remaining resources are enough to send the job."""
        return (self.av_jobs > 0 and
                self.av_cpu >= job['cpu'] and
                self.av_mem >= job['mem'])

    def actualize(self) -> None:
        """Remove picked up jobs from queuing system.
        Change status of newly finished jobs.
        """
        slurm_ids: NDArray[int32] = self.get_all_running()
        for q in self.queues:
            was_running = q['status'] == JobStatus.RUNNING.value
            # sub_ids that are not in the slurm_ids
            not_in_q: ndarray = (
                np.isin(element=q['sub_id'],
                        test_elements=slurm_ids,
                        assume_unique=True,
                        invert=True)
                )
            mask = np.logical_and(
                was_running, not_in_q
                )
            # Jobs that just finished, may have failed
            q['status'][mask] = JobStatus.FINISHED.value

            # Jobs to be picked up
            pu_jobs: NDArray = np.isin(
                q['status'],
                [JobStatus.PICKED_UP.value, JobStatus.FAILED.value])
            q['status'][pu_jobs] = JobStatus.NOT_IN_QUEUE.value

    def get_all_running(self) -> NDArray[int32]:
        """Create numpy array of job ids for fast comparaison
        with job ids in running list

        Returns:
            NDArray[int32]: job ids in return of command squeue -u user
        """
        process = Popen(args=['squeue', '-u', f'{getpass.getuser()}'],
                        shell=False, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        out, err = process.communicate()
        jobs: list[str] = out.decode().split('\n')[1:]
        slurm_ids: NDArray[int32] = np.zeros(len(jobs), dtype=np.int32)
        for i, j in enumerate(jobs[:-1]):
            slurm_ids[i] = int32(j.split()[0])
        return slurm_ids

    def status(self, id: int, jtype: str) -> JobStatus:
        """Get the status of a job."""
        if jtype == 'kin':
            return (JobStatus(self.kin_q[id]['status'])
                    if self.kin_q[id]['status']
                    else JobStatus.NOT_IN_QUEUE)
        elif jtype == 'sim':
            return (JobStatus(self.sim_q[id]['status'])
                    if self.sim_q[id]['status']
                    else JobStatus.NOT_IN_QUEUE)
        elif jtype == 'hlp':
            return (JobStatus(self.hlp_q[id]['status'])
                    if self.hlp_q[id]['status']
                    else JobStatus.NOT_IN_QUEUE)
        else:
            raise NotImplementedError('Unknown type of job')
