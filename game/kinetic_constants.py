from game.parameters import SOP
from game.writers.mess import MessWriter
import subprocess
import os
import getpass

class KinCon:
    """Wrapper around different calculators for kinetic constants calculation."""
    def __init__(self,
                 sop: SOP,
                 software='',
                 software_tpl='',
                 id='') -> None:
        
        self.SOP: SOP = sop
        self.software: str = software.casefold() 
        self.software_tpl: str = software_tpl
        self.id: str = id

    @property
    def output_name(self) -> str:
         if self.software == 'mess':
            return f"{self.id}.out"

    def calculate(self) -> None:
        if not os.path.isfile(self.output_name) or\
           os.path.getsize(self.output_name) == 0:
            self.create_input()
            self.submit()

    def create_input(self) -> None:
        if self.software == 'mess':
                mw = MessWriter(self.SOP, self.software_tpl)
                mw.write(f'{self.id}.inp')
        else:
             raise NotImplementedError(\
            "K constants calculation with this software not available yet")
        
    def submit(self) -> None:
        filename = f'{self.id}.slurm'
        if self.software == 'mess':
            from game.templates.slurm_mess import tpl
            submitscript = tpl.format(nprocs=8,
                                      filename=self.id,
                                      sub_queue='week-long-cpu',
                                      mem_mb=10000)
            with open(filename, 'w')as f:
                 f.write(submitscript)
            command = ['sbatch', filename]
            process = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = process.communicate()
            out = out.decode()
            self.job_id = out.split()[-1]

    def recover_rslts(self):
        """Wait for the results"""
        while not self.job_finished():
            pass

        with open(self.output_name, 'r') as f:
            rslt_file: list[str] = f.readlines()
            print(rslt_file)
                   
              
    def job_finished(self):
        if os.path.isfile(f"{self.id}.out"):
            return True
        
        command = ['squeue', '-u', f'{getpass.getuser()}']
        process = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate()
        out = out.decode()

        for line in out:
             if self.job_id == line.split()[0]:
                  return False
        if os.path.isfile(self.output_name):
            return True
        else:
            return False
             
        
         


