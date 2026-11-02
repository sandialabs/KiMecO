from enum import Enum
from genericpath import isfile
from kimeco.templates.pyjobarray import pyarrtpl
from kimeco.templates.kin_arr_tpl import kin_arr_tpl
from kimeco.templates.kin_arr_py_tpl import kin_arr_py_tpl
from kimeco.templates.slurm import slurmtpl
from kimeco.templates.slurm_arr import slurmarrtpl
from kimeco.templates.pyjob import pytpl
from kimeco.writers.prompt_collector import PromptCollectorFiles, is_prompt_run
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


#: Value of the ``collector_id`` field of a kin job when the sbatch of its
#: prompt collector failed (a Slurm job id is always positive; 0 means "no
#: collector").
COLLECTOR_SUBMIT_FAILED: int = -1

#: Outputs of a MESS run that share the ``<kin name>P<slot>`` stem with the
#: rate output but are not rate outputs (PED and microcanonical outputs).
SIDE_OUTPUT_SUFFIXES: tuple[str, ...] = ('_ped.out', '_ke.out')


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

        self.pyarrtpl: str = pyarrtpl
        self.q_name: str = self.settings['q_name']
        self.messtpl = kin_arr_tpl

        # Define a dtype object to create a structured numpy array.
        # collector_id: Slurm id of the prompt collector of a kin job
        # (prompt mode, submitted after the array with afterok); 0 = no
        # collector (non-prompt kin job, every sim job);
        # COLLECTOR_SUBMIT_FAILED = its sbatch failed.
        self.jobdata = np.dtype(dtype=[
            ('sub_id', int32),
            ('name', str_, (20)),
            ('loc', str_, (150)),
            ('status', str_, (10)),
            ('cpu', int16),
            ('mem', int32),
            ('type', str_, (3)),
            ('n_pes', int16),
            ('collector_id', int32)])

        self.kin_q: NDArray[Any] = np.empty(shape=(nel), dtype=self.jobdata)
        self.sim_q: NDArray[Any] = np.empty(shape=(nel), dtype=self.jobdata)
        self.queues: list[NDArray] = [self.kin_q, self.sim_q]
        self.queues_order: list[str] = ['kin', 'sim']

        self.submitted: int = 0
        self.running: int = 0

    @property
    def av_jobs(self) -> int:
        kin_running = self.kin_q[
            self.kin_q['status'] == JobStatus.RUNNING.value
        ]
        job_sum = int(np.sum(kin_running['n_pes']))
        job_sum += \
            len(self.sim_q[
                self.sim_q['status'] == JobStatus.RUNNING.value
            ]) *\
            self.n_exp
        return min(
            self._max_jobs - job_sum,
            self.settings['max_user_jobs'] - self.current_user_jobs)

    @property
    def av_cpu(self) -> int:
        kin_running = self.kin_q[
            self.kin_q['status'] == JobStatus.RUNNING.value
        ]
        cpu_sum = np.sum(kin_running['cpu'] * kin_running['n_pes'])
        cpu_sum += np.sum(
            self.sim_q[
                self.sim_q['status'] == JobStatus.RUNNING.value
            ]['cpu']) *\
            self.n_exp
        return self._max_cpu - cpu_sum

    @property
    def av_mem(self) -> float:
        kin_running = self.kin_q[
            self.kin_q['status'] == JobStatus.RUNNING.value
        ]
        mem_sum = np.sum(kin_running['mem'] * kin_running['n_pes'])
        mem_sum += np.sum(
            self.sim_q[
                self.sim_q['status'] == JobStatus.RUNNING.value
            ]['mem']) *\
            self.n_exp
        return self._max_mem - mem_sum

    @property
    def n_ready(self) -> int:
        n_ready: int = len(
            self.kin_q[self.kin_q['status'] == JobStatus.READY.value]
        )
        n_ready += len(
            self.sim_q[self.sim_q['status'] == JobStatus.READY.value]
        )
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
           instance. In prompt mode a kin job also gets the submission file
           of its prompt collector.

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
             cpu, mem, jtype, n_pes, 0)],
            dtype=self.jobdata)
        self.create_sub_file(job=job, n_pes=n_pes)

        if jtype == 'kin':
            self.kin_q[idx] = job[0]
        elif jtype == 'sim':
            self.sim_q[idx] = job[0]

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
            raise NotImplementedError('Unknown job type')
        job_cmd: str

        if job['type'] == 'kin':
            tpl = (kin_arr_py_tpl
                   if self.settings.get('use_automech', False)
                   else self.messtpl)
            job_cmd = tpl.format(filename=str(job['name'][0]))
        elif job['type'] == 'sim':
            filenames = [
                f"{str(job['name'][0])}_exp{exp.tpl_idx:02d}.py"
                for exp in self.settings['experiments']]
            job_cmd = self.pyarrtpl.format(
                filename=str(job['name'][0]),
                filenames=' '.join(filenames),
                scratchdir=scratchdir,
                destination=job['loc'][0])
        else:
            raise NotImplementedError('Unknown job type')

        sub_file: str = sub_cmd + job_cmd

        with open(f"{job['loc'][0]}/{job['name'][0]}.{self.ext}", 'w') as f:
            f.write(sub_file)

        if job['type'][0] == 'kin' and is_prompt_run(self.settings):
            self._write_collector_sub_file(job=job)

    def _write_collector_sub_file(self,
                                  job: NDArray[Any]) -> None:
        """Write the Slurm submission file of a kin job's prompt collector.

        One single job (not an array): 1 CPU, the memory of the kin job,
        logs ``logs/prompt_<kin name>.stdout|.err`` (they do not match the
        ``logs/<kin name>_*`` glob of the array tasks), no display
        (``MPLBACKEND=Agg``), then ``python prompt_<kin name>.py`` with the
        ``python`` of the submitting environment.

        Args:
            job (NDArray[Any]): one-element array of the kin job (dtype
                jobdata).
        """
        files = PromptCollectorFiles(loc=str(job['loc'][0]),
                                     kin_name=str(job['name'][0]))
        sub_cmd: str = self.subtpl.format(
            nprocs=1,
            exclude_nodes=self.settings['exclude_nodes'],
            filename=files.stem,
            sub_queue=self.q_name,
            mem_mb=job['mem'][0])
        content: str = (sub_cmd + "\nexport MPLBACKEND=Agg"
                        + pytpl.format(filename=files.stem))
        with open(files.slurm, 'w') as f:
            f.write(content)

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
            p_outs: list[str] = [
                f for f in sorted(glob.glob(f"{base}P*.out"))
                if not os.path.basename(f).startswith('_')
            ]
            for p_out in p_outs:
                os.remove(p_out)
            return clear_err

        p_outs: list[str] = self._rate_outputs(base)
        if len(p_outs) != n_pes:
            return clear_err

        p_errs: list[str] = [
            f for f in glob.glob(f"{base}P*.err")
            if not os.path.basename(f).startswith('_')
        ]
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

    @staticmethod
    def _rate_outputs(base: str) -> list[str]:
        """Rate outputs of a kin job, one per PES: ``<base>P<slot>.out``.

        Leading-underscore pass-1 copies and the PED and microcanonical
        outputs (``_ped.out``, ``_ke.out``, written in every mode when an
        input asks for them) are not rate outputs.

        Args:
            base (str): ``<loc>/<kin name>``.

        Returns:
            list[str]: sorted paths of the rate outputs.
        """
        return [
            f for f in sorted(glob.glob(f"{base}P*.out"))
            if not os.path.basename(f).startswith('_')
            and not f.endswith(SIDE_OUTPUT_SUFFIXES)
        ]

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

    def clean_files(self,
                    job: NDArray[Any],
                    clear_err: bool) -> None:
        """Erase all files except the output
        if the job finished without error.

        In prompt mode a kin job keeps every file when it failed (inputs,
        ``.log``, PED outputs, collector files, for diagnosis). When it was
        picked up (after its collector ended and its prompt-rates file was
        checked) the PED outputs and the collector script and submission
        file are removed too. The prompt-rates file and ``logs/`` are kept.

        Args:
            job (NDArray[Any]): Array of the job with custom datatype.
        """
        # Don't delete files for jobs that need to be resubmitted
        if job['status'] == JobStatus.READY.value:
            return
        prompt_kin: bool = (job['type'] == 'kin'
                            and is_prompt_run(self.settings))
        if prompt_kin and job['status'] != JobStatus.PICKED_UP.value:
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
            for p_log in glob.glob(f"{base}P*.log"):
                os.remove(p_log)
            # Automech-driven runs leave per-slot python driver scripts,
            # MESS inputs and leading-underscore pass-1 outputs. On success
            # remove them; on failure keep the .py scripts and .inp files so
            # the job can be resubmitted.
            if job['status'] == JobStatus.PICKED_UP.value:
                for p_py in glob.glob(f"{base}P*.py"):
                    os.remove(p_py)
                for p_inp in glob.glob(f"{base}P*.inp"):
                    os.remove(p_inp)
                underscore_base: str = f"{job['loc']}/_{job['name']}"
                for p_pass1 in glob.glob(f"{underscore_base}P*.out"):
                    os.remove(p_pass1)
                if prompt_kin:
                    for suffix in SIDE_OUTPUT_SUFFIXES:
                        for p_side in glob.glob(f"{base}P*{suffix}"):
                            os.remove(p_side)
                    files = PromptCollectorFiles(loc=str(job['loc']),
                                                 kin_name=str(job['name']))
                    for path in (files.script, files.slurm):
                        if os.path.exists(path):
                            os.remove(path)

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
        if job['type'] == 'kin' and is_prompt_run(self.settings):
            job['collector_id'] = np.int32(
                self._submit_collector(job=job, array_id=slurm_id))

    def _submit_collector(self,
                          job,
                          array_id: int) -> int:
        """Submit the prompt collector of a kin job after its array.

        ``--dependency=afterok:<array id>``: the collector starts only when
        every task of the array ended with exit code 0.
        ``--kill-on-invalid-dep=yes``: Slurm cancels it when a task failed,
        instead of keeping it pending forever. Never raises: a failed
        sbatch is logged and recorded as ``COLLECTOR_SUBMIT_FAILED``, the
        array keeps running and RateCo stops the run at its next pass.
        Runs in the job folder (``submit`` changed to it).

        Args:
            job: Numpy structured array of the kin job. dtype = jobdata
            array_id (int): Slurm id of the job's array.

        Returns:
            int: Slurm id of the collector, or COLLECTOR_SUBMIT_FAILED.
        """
        files = PromptCollectorFiles(loc=str(job['loc']),
                                     kin_name=str(job['name']))
        command: list[str] = [
            'sbatch',
            f'--dependency=afterok:{array_id}',
            '--kill-on-invalid-dep=yes',
            f'{files.stem}.{self.ext}']
        try:
            process = Popen(args=command,
                            shell=False,
                            stdout=PIPE,
                            stdin=PIPE,
                            stderr=PIPE)
            out, err = process.communicate()
            if process.returncode != 0:
                raise RuntimeError(err.decode().strip())
            collector_id: int = int(out.decode().split()[-1])
        except (OSError, RuntimeError, ValueError, IndexError) as exc:
            self.klog.error(
                f"Failed to submit the prompt collector of {job['name']} "
                f"(array {array_id}): {exc}")
            return COLLECTOR_SUBMIT_FAILED
        self.klog.info(
            f"Prompt collector of {job['name']} submitted as job "
            f"{collector_id} (afterok:{array_id}).")
        return collector_id

    def collector_submit_failed(self,
                                idx: int) -> bool:
        """Tell whether the prompt collector of a kin job could not be
        submitted.

        Only jobs submitted by this process (status RUNNING or FINISHED)
        are considered: the fields of an unused queue slot are undefined.

        Args:
            idx (int): position of the job in the kin queue.

        Returns:
            bool: True when the collector sbatch failed.
        """
        job = self.kin_q[idx]
        return (job['status'] in (JobStatus.RUNNING.value,
                                  JobStatus.FINISHED.value)
                and int(job['collector_id']) == COLLECTOR_SUBMIT_FAILED)

    def run(self) -> None:
        """Run all jobs of the workflow in parallel
        as long as ressources are available.
        """
        here: str = os.getcwd()
        # Refresh user queue occupancy before trying any submission so
        # max_user_jobs is enforced on the very first scheduling decision.
        self.current_user_jobs = len(self.get_all_running())
        for q, jtype in zip(self.queues, self.queues_order):
            for idx, rdy in enumerate(q['status'] == JobStatus.READY.value):
                if rdy:
                    if self.enough_resources_for(job=q[idx], jtype=jtype):
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

        A job with a prompt collector is finished only when neither its
        array nor its collector is in the Slurm queue (a collector id of 0
        or COLLECTOR_SUBMIT_FAILED is never a Slurm id).
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
            # collector ids that are not in the slurm_ids (the column holds
            # many 0: not unique)
            collector_gone: ndarray = np.isin(element=q['collector_id'],
                                              test_elements=slurm_ids,
                                              invert=True)
            mask = np.logical_and(
                np.logical_and(was_running, not_in_q), collector_gone
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
        jobids: list[str] = [
            jobid.strip('"').strip()
            for jobid in out.decode().split('\n')[1:]
        ]
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
        base: str = str(job['loc']) + '/' + str(job['name'])
        if job['type'] == 'kin':
            n_pes: int = int(job['n_pes']) if int(job['n_pes']) > 0 else 1
            if self.settings.get('use_automech', False):
                p_files: list[str] = [
                    f for f in sorted(glob.glob(base + 'P*.py'))
                    if not os.path.basename(f).startswith('_')
                ]
            else:
                p_files = sorted(glob.glob(base + 'P*.inp'))
            drivers_ready: bool = (
                len(p_files) == n_pes and
                all(os.stat(p_file).st_size > 0 for p_file in p_files))
            if drivers_ready and is_prompt_run(self.settings):
                # The array is never submitted without its collector.
                files = PromptCollectorFiles(loc=str(job['loc']),
                                             kin_name=str(job['name']))
                return all(os.path.isfile(path)
                           and os.stat(path).st_size > 0
                           for path in (files.script, files.slurm))
            return drivers_ready
        elif job['type'] == 'sim':
            n_unique_scripts: int = len(set(
                exp.tpl_idx for exp in self.settings['experiments']
            ))
            scripts: list[str] = sorted(glob.glob(base + '_*.py'))
            return (len(scripts) == n_unique_scripts and
                    all(os.stat(script).st_size > 0 for script in scripts))
        else:
            raise NotImplementedError('Unknown file type')
