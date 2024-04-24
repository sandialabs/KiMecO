class Rotor:
    """Rorot object:
    describe atoms involved in rotor"""
    def __init__(self,
                 ThermalPowerMax: float,
                 group: list[int],
                 axis: list[int],
                 symmetry: int,
                 scan: list[float]) -> None:
        
        self.ThermalPowerMax: float = ThermalPowerMax
        self.group: list[int] = group
        self.axis: list[int] = axis
        self.symmetry: int = symmetry
        self.scan: list[float] = scan
        
