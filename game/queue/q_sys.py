import os
from game.templates.pyjob import pytpl
from game.templates.messjob import messtpl
from game.templates.slurm import slurmtpl
from subprocess import Popen, PIPE


class QueueingSystem:
    def __init__(self,
                 max_jobs: int,
                 max_cpu: int,
                 max_mem: int,
                 cpu_job: int = 1,
                 mem_job: float = 500.0,
                 q_type: str = 'slurm',
                 q_name: str = 'day-long-cpu'
                 ) -> None:
        """The queueing system is only meant to manage the number of jobs
        and the ressources used by the workflow. The run() method should only submit jobs
        to use a maximum of ressources. But it should not:
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
            mem_job (float, optional): Quantity of memory (Mb) used
                                       for each job. Defaults to 500.0.
            location (str, optional): Where jobs should be submitted from.
                                      Defaults to local.
        """

        self.queue: list = []
        self.av_jobs: int = max_jobs
        self.av_cpu: int = max_cpu
        self.av_mem: int = max_mem
        self.cpu_job: int = cpu_job
        self.mem_job: float = mem_job
        if q_type.casefold() == 'slurm':
            self.subtpl: str = slurmtpl
            self.ext: str = 'slurm'
        else:
            raise NotImplementedError('Slurm is the only q_type available.')
        self.pytpl: str = pytpl
        self.messtpl: str = messtpl
        self.q_name: str = q_name
        self.queue: list = []

    def add_to_q(self,
                 location: str,
                 filename: str,
                 jtype: str,
                 ressources: tuple[int, int]
                 ) -> None:
        """Create the submission file when job is added to queue.
           Job file itself must have already been created by the submitting
           instance.

        Args:
            location (str): Absolute path to the folder
            filename (str): filename without extension
            jtype (str): <kin> (for kinetic) or <sim> (simulation)
            ressources (tuple[int, int]): number of CPU and memory (Mb)
        """
        self.create_sub_file(location=location,
                             filename=filename,
                             jtype=jtype,
                             ressources=ressources)
        self.queue.append((location, filename, ressources))

    def create_sub_file(self,
                        location: str,
                        filename: str,
                        jtype: str,
                        ressources: tuple[int, int]
                        ) -> None:
        cpu: int
        mem: int  # In Mb
        (cpu, mem) = ressources
        sub_cmd: str = self.subtpl.format(nprocs=cpu,
                                          filename=filename,
                                          sub_queue=self.q_name,
                                          mem_mb=mem
                                          )
        if jtype == 'kin':
            job_cmd: str = self.messtpl.format(filename=filename)
        elif jtype == 'sim':
            job_cmd: str = self.pytpl.format(filename=filename)

        sub_file: str = sub_cmd + job_cmd

        with open(f'{location}/{filename}.{self.ext}', 'w') as f:
            f.write(sub_file)

    def submit(self,
               job: tuple[str, str]) -> int:
        """Go in the submission directory,
        submit the job, and return the slurm's job id.

        Args:
            location (str): Submission directory. Absolute path.
            filename (str): Submission script name, without extension.

        Returns:
            int: Slurm's job ID
        """
        location: str
        filename: str
        (location, filename) = job
        os.chdir(location)
        command: list[str] = ['sbatch', filename+'.'+self.ext]
        process = Popen(args=command,
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        outstr: str = out.decode()
        slurm_id: int = int(outstr.split()[-1])
        return slurm_id

    # def submit(self,
    #            sim: ct.Solution,
    #            id: str
    #            ) -> None:
    #     self.serialize_sim(sim=sim,
    #                        name=f'sim_{id}')

    # def serialize_sim(self,
    #                   sim: ct.Solution,
    #                   name: str) -> None:
    #     with open(f'{self.location}/{name}.pkl', 'wb') as pkl_file:
    #         pickle.dump([sim], pkl_file)
