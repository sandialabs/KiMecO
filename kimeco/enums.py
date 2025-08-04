from enum import Enum


class ElementStatus(Enum):
    SOP = 'sop'
    KIN = 'kin'
    SIM = 'sim'
    SCORING = 'scoring'
    TO_SAVE = 'to_save'
    DONE = 'DONE'
    RESET = 'reset'


class Ptype(Enum):
    WE = 'we'  # Well energy
    BE = 'be'  # Barrier energy
    SIG = 'sigma'  # Lenard Jones potential
    EPSI = 'epsilon'  # Lenard Jones potential
    ETF = 'fact'  # Energy Transfert Factor
    ETP = 'pow'  # Energy Transfert Power
    IF = 'if'  # Imaginary Frequency
    IFC = 'freq'  # individual frequency coefficient
    BFC = 'bfc'  # Batch frequencies coefficient
    HRS = 'hrs'  # Hindered Rotor Scan
    MRC = 'mrc'  # Multudimensional Rotor Coefficient
    SFC = 'sfc'  # Symmetry Factor Coefficient
    SCORE = 'score'


class Pclass(Enum):
    ADDITIVE = {
            Ptype.WE.value,
            Ptype.BE.value,
            Ptype.ETP.value}
    MULTIPLICATIVE = {
            Ptype.SFC.value,
            Ptype.MRC.value,
            Ptype.BFC.value,
            Ptype.IFC.value
            }
    PERCENT = {
            Ptype.IF.value,
            Ptype.HRS.value,
            Ptype.SIG.value,
            Ptype.EPSI.value,
            Ptype.ETF.value}


class FreqMode(Enum):
    BATCH = 'batch'
    INDIVIDUAL = 'individual'


class Distrib(Enum):
    UNIFORM = 'uniform'
    LOGUNIFORM = 'log-uniform'
    NORMAL = 'normal'
    LOGNORMAL = 'log-normal'
