class Job:
    def __init__(self,
                 id: str,
                 location: str,
                 cpu: int,
                 mem: int,
                 jtype: str) -> None:

        self.sub_id: int  # Defined at the submission
        self.name: str = id
        self.loc: str = location
        self.status: str = 'ready'
        self.cpu: int = cpu
        self.mem: int = mem
        self.type: str = jtype
