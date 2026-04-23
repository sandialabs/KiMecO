from enum import Enum
from genericpath import isfile
from kimeco.templates.pyjob import pytpl
from kimeco.templates.pyjobarray import pyarrtpl
from kimeco.templates.kin_arr_tpl import kin_arr_tpl
from kimeco.templates.slurm import slurmtpl
from kimeco.templates.slurm_arr import slurmarrtpl
from subprocess import Popen, PIPE
import numpy as np
from numpy.typing import NDArray
from numpy import int16, int32, ndarray, str_
from typing import Any
import getpass
import glob
import os
from kimeco.logger_config import KMOLogger
import time


class JobStatus(Enum):
    READY = 'ready'
    RUNNING = 'running'
    FINISHED = 'finished'
    PICKED_UP = 'pickedUp'
    FAILED = 'fail'
    NOT_IN_QUEUE = 'notInQueue'


class QueueingSystem:
    def __init__(self,
                 settings: dict[str, Any],
                 nel: int,
                 nhlp: int,
                 klog: KMOLogger,
                 q_type: str = 'slurm',
                 q_name: str = 'day-long-cpu',
                 ) -> None:
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
        self.klog: KMOLogger = klog
        self.settings: dict[str, Any] = settings
        self._max_jobs: int = self.settings['max_jobs']
        self._max_cpu: int = self.settings['max_cpu']
        self._max_mem: int = self.settings['max_mem']
        self.cpu_kin: int = self.settings['cpu_kin']
        self.cpu_sim: int = self.settings['cpu_sim']
        self.mem_kin: int = self.settings['mem_kin']
        self.mem_sim: int = self.settings['mem_sim']
        self.current_user_jobs: int = 0
        self.n_exp: int = self.settings['n_exp']

        if q_type.casefold() == 'slurm':
            self.subtpl: str = slurmtpl
            self.sub_arr_tpl: str = slurmarrtpl
            self.ext: str = 'slurm'
            exclude_substr = 'exclude'
        else:
            raise NotImplementedError('Slurm is the only q_type available.')
        if len(self.settings['exclude_nodes']) == 0:
            for line in self.subtpl.split('\n'):
                if exclude_substr in line:
                    break
            self.subtpl = self.subtpl.replace(line, '')

        self.pytpl: str = pytpl
        self.pyarrtpl: str = pyarrtpl
        self.q_name: str = q_name
        self.messtpl = kin_arr_tpl

        # Define a dtype object to create a structured numpy array.
        self.jobdata = np.dtype(dtype=[
            ('sub_id', int32),
            ('name', str_, (20)),
            ('loc', str_, (150)),
            ('status', str_, (10)),
            ('cpu', int16),
            ('mem', int32),
            ('type', str_, (3)),
            ('n_pes', int16)])

        self.kin_q: NDArray[Any] = np.empty(shape=(nel), dtype=self.jobdata)
        self.sim_q: NDArray[Any] = np.empty(shape=(nel), dtype=self.jobdata)
        self.hlp_q: NDArray[Any] = np.empty(shape=(nhlp), dtype=self.jobdata)
        self.queues: list[NDArray] = [self.kin_q, self.sim_q, self.hlp_q]
        self.queues_order: list[str] = ['kin', 'sim', 'hlp']

        self.submitted: int = 0
        self.running: int = 0

    @property
    def av_jobs(self) -> int:
        kin_running = self.kin_q[self.kin_q['status'] == JobStatus.RUNNING]
        job_sum = int(np.sum(kin_running['n_pes']))
        job_sum += \
            len(self.sim_q[self.sim_q['status'] == JobStatus.RUNNING]) *\
            self.n_exp
        job_sum += len(self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING])
        return min(
            self._max_jobs - job_sum,
            self.settings['max_user_jobs'] - self.current_user_jobs)

    @property
    def av_cpu(self) -> int:
        kin_running = self.kin_q[self.kin_q['status'] == JobStatus.RUNNING]
        cpu_sum = np.sum(kin_running['cpu'] * kin_running['n_pes'])
        cpu_sum += np.sum(
            self.sim_q[self.sim_q['status'] == JobStatus.RUNNING]['cpu']) *\
            self.n_exp
        cpu_sum += np.sum(
            self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING]['cpu'])
        return self._max_cpu - cpu_sum

    @property
    def av_mem(self) -> float:
        kin_running = self.kin_q[self.kin_q['status'] == JobStatus.RUNNING]
        mem_sum = np.sum(kin_running['mem'] * kin_running['n_pes'])
        mem_sum += np.sum(
            self.sim_q[self.sim_q['status'] == JobStatus.RUNNING]['mem']) *\
            self.n_exp
        mem_sum += np.sum(
            self.hlp_q[self.hlp_q['status'] == JobStatus.RUNNING]['mem'])
        return self._max_mem - mem_sum

    @property
    def n_ready(self) -> int:
        n_ready: int = len(self.kin_q[self.kin_q['status'] == JobStatus.READY])
        n_ready += len(self.sim_q[self.sim_q['status'] == JobStatus.READY])
        n_ready += len(self.hlp_q[self.hlp_q['status'] == JobStatus.READY])
        return n_ready

    def add_to_q(self,
                 name: str,
                 idx: int,
                 location: str,
                 jtype: str,
                 ressources: tuple[int, int],
                 n_pes: int = 1) -> None:
        """Create the submission file when job is added to queue.
           Job file itself must have already been created by the submitting
           instance.

        Args:
            location (str): Absolute path to the folder
            name (str): filename without extension
            idx (int): position in the queue of type jtype
            jtype (str): <kin> (for kinetic) or <sim> (simulation)
            ressources (tuple[int, int]): number of CPU and memory (Mb)
            n_pes (int): number of PES input/output files for kinetic jobs
        """
        cpu, mem = ressources
        job: NDArray[Any] = np.array([
            (0, name, location, JobStatus.READY.value,
             cpu, mem, jtype, n_pes)],
            dtype=self.jobdata)
        self.create_sub_file(job=job, n_pes=n_pes)

        if jtype == 'kin':
            self.kin_q[idx] = job[0]
        elif jtype == 'sim':
            self.sim_q[idx] = job[0]
        elif jtype == 'hlp':
            self.hlp_q[idx] = job[0]

    def create_sub_file(self,
                        job: NDArray[Any],
                        n_pes: int = 1) -> None:
        """Create the submission script for the job."""
        if job['type'] == 'sim':
            scratchdir: str = self.settings['scratch_base'] +\
                              self.settings["project_name"] + '/' +\
                              job['name'][0]
            sub_cmd: str = self.sub_arr_tpl.format(
                n_exp=self.n_exp-1,
                exclude_nodes=self.settings['exclude_nodes'],
                nprocs=job['cpu'][0],
                filename=str(job['name'][0]),
                sub_queue=self.q_name,
                mem_mb=job['mem'][0],
                scratchdir=scratchdir
            )
        elif job['type'] == 'kin':
            sub_cmd = self.sub_arr_tpl.format(
                n_exp=n_pes-1,
                exclude_nodes=self.settings['exclude_nodes'],
                nprocs=job['cpu'][0],
                filename=str(job['name'][0]),
                sub_queue=self.q_name,
                mem_mb=job['mem'][0],
                scratchdir=job['loc'][0]
            )
        else:
            sub_cmd: str = self.subtpl.format(
                exclude_nodes=self.settings['exclude_nodes'],
                nprocs=job['cpu'][0],
                filename=str(job['name'][0]),
                sub_queue=self.q_name,
                mem_mb=job['mem'][0]
            )
        job_cmd: str

        if job['type'] == 'kin':
            job_cmd = self.messtpl.format(filename=str(job['name'][0]))
        elif job['type'] == 'hlp':
            job_cmd = self.pytpl.format(filename=str(job['name'][0]))
        elif job['type'] == 'sim':
            job_cmd = self.pyarrtpl.format(
                filename=str(job['name'][0]),
                scratchdir=scratchdir,
                destination=job['loc'][0])
        else:
            raise NotImplementedError('Unknown job type')

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
        else:
            raise NotImplementedError('Unknown job type')

        if job['status'] not in [
                JobStatus.RUNNING.value,
                JobStatus.FINISHED.value]:
            return

        if jtype == 'kin':
            clear_err: bool = self._pickup_kin(job)
        elif jtype == 'sim':
            clear_err = self._pickup_sim(job)
        elif jtype == 'hlp':
            clear_err = self._pickup_hlp(job)

        if job['status'] in [
                JobStatus.PICKED_UP.value,
                JobStatus.FAILED.value]:
            self.clean_files(job, clear_err=clear_err)

    def _pickup_kin(self,
                    job) -> bool:
        clear_err = True
        base: str = f"{job['loc']}/{job['name']}"
        lfile: str = f"{job['loc']}/logs/{job['name']}"
        n_pes: int = int(job['n_pes'])

        lerrs: list[str] = []
        while len(lerrs) < n_pes:
            time.sleep(0.1)
            lerrs = sorted(glob.glob(f"{lfile}_*.err"))

        if any(os.stat(lerr).st_size > 0 for lerr in lerrs):
            job['status'] = JobStatus.FAILED.value
            clear_err = False
            self.klog.warning(
                f"Resetting job {job['name']} because an error occurred.")
            p_outs: list[str] = sorted(glob.glob(f"{base}P*.out"))
            for p_out in p_outs:
                os.remove(p_out)
            return clear_err

        p_outs: list[str] = sorted(glob.glob(f"{base}P*.out"))
        if len(p_outs) != n_pes:
            return clear_err

        p_errs: list[str] = glob.glob(f"{base}P*.err")
        if any(os.stat(p_err).st_size > 0 for p_err in p_errs):
            job['status'] = JobStatus.FAILED.value
            clear_err = False
            self.klog.warning(
                f"Resetting job {job['name']} because an error occurred.")
            for p_out in p_outs:
                os.remove(p_out)
        else:
            job['status'] = JobStatus.PICKED_UP.value
        return clear_err

    def _pickup_sim(self,
                    job) -> bool:
        clear_err = True
        successful: bool = True
        for exp in range(self.n_exp):
            lfile: str = f"{job['loc']}/logs/{job['name']}_{exp}"
            while not (os.path.exists(f"{lfile}.err")):
                time.sleep(0.1)
                if os.stat(f"{lfile}.err").st_size > 0:
                    successful = False
                self.klog.warning(
                    f"Simulation {exp} of {job['name']} has an error.")
        if not successful:
            job['status'] = JobStatus.FAILED.value
            clear_err = False
            self.klog.warning(
                f"Resetting job {job['name']} because an error occurred.")
        else:
            job['status'] = JobStatus.PICKED_UP.value
        return clear_err

    def _pickup_hlp(self,
                    job) -> bool:
        clear_err = True
        lfile: str = f"{job['loc']}/logs/{job['name']}"
        if os.path.exists(f"{lfile}.err") and\
           os.stat(f"{lfile}.err").st_size > 0:
            job['status'] = JobStatus.FAILED.value
            clear_err = False
            self.klog.info(f"Helper {job['name'][0]} failed.")
        else:
            job['status'] = JobStatus.PICKED_UP.value
        return clear_err

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
        for ext in ['log', 'aux', 'slurm']:
            if ext == 'err' and not clear_err:
                continue
            if os.path.exists(f"{job['loc']}/{job['name']}.{ext}"):
                os.remove(f"{job['loc']}/{job['name']}.{ext}")

        if job['type'] == 'kin':
            base: str = f"{job['loc']}/{job['name']}"
            for p_aux in glob.glob(f"{base}P*.aux"):
                os.remove(p_aux)

    def submit(self, job) -> None:
        """Submit the job, and return the slurm's job id.
        Set the Job's status to <running>.

        Args:
            job: Numpy structured array. dtype = jobdata

        """
        if os.getcwd() != str(job['loc']):
            os.chdir(str(job['loc']))
        sub_file: str = str(job['name']) + '.' + self.ext
        i = 0
        # Make sure the submission file is created
        while not isfile(sub_file):
            if i > 10:
                self.klog.warning(
                    f'SLURM submission script missing for {sub_file}')
                return
            time.sleep(1)
            i += 1
        else:
            if not os.stat(sub_file).st_size > 0:
                time.sleep(1)
        # Make sure all necessary files for the job are created
            i = 0
        while not self.factually_ready(job):
            if i > 10:
                self.klog.warning(f'Missing files for {sub_file}')
                return
            time.sleep(1)
            i += 1
        command: list[str] = [
            'sbatch', sub_file]
        process = Popen(args=command,
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        outstr: str = out.decode()
        if process.returncode != 0:
            msg: str = f"Failed to submit {job['name']}" +\
                f": {err.decode().strip()}"
            self.klog.error(msg)
            return  # Handle the error appropriately
        slurm_id: int = int(outstr.split()[-1])
        job['sub_id'] = np.int32(slurm_id)
        job['status'] = JobStatus.RUNNING.value

    def run(self) -> None:
        """Run all jobs of the workflow in parallel
        as long as ressources are available.
        """
        here: str = os.getcwd()
        for q, jtype in zip(self.queues, self.queues_order):
            for idx, rdy in enumerate(q['status'] == JobStatus.READY.value):
                if rdy:
                    if self.enough_resources_for(
                        job=q[idx],
                        jtype=jtype):
                        self.submit(job=q[idx])
                    else:
                        self.actualize()
                        break
        if self.n_ready <= self.av_jobs:
            self.actualize()
        os.chdir(here)

    def enough_resources_for(self,
                             job,
                             jtype: str) -> bool:
        """Check if remaining resources are enough to send the job."""
        if jtype == 'sim':
            return (self.av_jobs >= self.n_exp and
                    self.av_cpu >= job['cpu']*self.n_exp and
                    self.av_mem >= job['mem']*self.n_exp)
        else:
            n_pes: int = int(job['n_pes'])
            return (self.av_jobs >= n_pes and
                    self.av_cpu >= job['cpu'] * n_pes and
                    self.av_mem >= job['mem'] * n_pes)

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
        process = Popen(args=[
            'squeue',
            '-u',
            f'{getpass.getuser()}',
            '--format=\"%.20F\"'],
                        shell=False, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        out, err = process.communicate()
        jobids: list[str] = [jobid.strip('"').strip() for jobid in out.decode().split('\n')[1:]]
        slurm_ids: NDArray[int32] = np.array(
            jobids[:-1],
            dtype=np.int32)
        self.current_user_jobs = len(slurm_ids)
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

    def factually_ready(self,
                        job) -> bool:
        """Check if the files necessary for the job
        have finished being written before submitting.
        Args:
            job: Numpy structured array. dtype = jobdata

        Returns:
            bool: All necessary files are there.
        """
        # Helpers only need JSON, and their existence is checked elsewhere.
        base: str = str(job['loc']) + '/' + str(job['name'])
        if job['type'] == 'hlp':
            return (isfile(base + '.py')
                    and os.stat(base + '.py').st_size > 0)
        elif job['type'] == 'kin':
            n_pes: int = int(job['n_pes']) if int(job['n_pes']) > 0 else 1
            p_inps: list[str] = sorted(glob.glob(base + 'P*.inp'))
            return (len(p_inps) == n_pes and
                    all(os.stat(p_inp).st_size > 0 for p_inp in p_inps))
        elif job['type'] == 'sim':
            scripts: list[str] = sorted(glob.glob(base + '_*.py'))
            return (len(scripts) == self.n_exp and
                    all(os.stat(script).st_size > 0 for script in scripts))
        else:
            raise NotImplementedError('Unknown file type')
