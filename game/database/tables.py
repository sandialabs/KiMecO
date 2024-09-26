from typing import Any, List, Optional
from sqlalchemy import String, Integer, Float
from sqlalchemy.types import PickleType
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class Base(DeclarativeBase):
    pass


class SimTable(Base):
    __tablename__: str = "sim"
    sim_id: Mapped[str] = mapped_column(String(15), primary_key=True)
    times: Mapped[PickleType] = mapped_column(PickleType)
    kin: Mapped["KinTable"] = relationship(back_populates="sims")

    def __init__(self,
                 headers: list[str]) -> None:
        super().__init__()
        self.headers: dict[str, Mapped[PickleType]] = {}
        for col in headers:
            self.headers[col] = mapped_column(PickleType)

    def __repr__(self) -> str:
        rpr = f"sim(sim_id={self.sim_id!r}, times={self.times!r}"
        for col in self.headers:
            rpr += f', {col}={self.headers[col]!r}'
        rpr += ')'
        return rpr


class KinTable(Base):
    __tablename__: str = "kin"
    kin_id: Mapped[str] = mapped_column(String(15), primary_key=True)
    pres: Mapped[Float] = mapped_column(Float(32))
    temp: Mapped[Float] = mapped_column(Float(32))
    species: Mapped[String] = mapped_column(String(15))
    sop: Mapped["SopTable"] = relationship(back_populates="kin")
    sims: Mapped[List["SimTable"]] = relationship(back_populates="kin")

    def __init__(self,
                 headers: list[str]) -> None:
        super().__init__()
        self.headers: dict[str, Mapped[PickleType]] = {}
        for col in headers:
            self.headers[col] = mapped_column(PickleType)

    def __repr__(self) -> str:
        rpr: str = f"kin(kin_id={self.kin_id!r}"
        rpr += f", pres={self.pres!r}"
        rpr += f", temp={self.temp!r}"
        rpr += f", species={self.species!r}"
        for col in self.headers:
            rpr += f', {col}={self.headers[col]!r}'
        rpr += ')'
        return rpr


class SopTable(Base):
    __tablename__: str = "sop"
    sop_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kin: Mapped["KinTable"] = relationship(back_populates="sop")
    headers: list[tuple[str, Mapped[Float]]] =  mapped_column(Float(32))

    def __repr__(self) -> str:
        rpr: str = f"sop(sop_id={self.sop_id!r}"
        for col in self.headers:
            rpr += f', {col}={self.headers[col]!r}'
        rpr += ')'
        return rpr
    