from pydantic import BaseModel
from typing import Optional, List



class CommitteeParent(BaseModel):
    name: str
    systemCode: str
    url: str


class Subcommittees(BaseModel):
    name: str
    systemCode: str
    url: str


class Committee(BaseModel):
    chamber: str
    committeeTypeCode: str
    updateDate: str
    name: str
    parent: Optional[CommitteeParent] = None
    subcommittees: Optional[List[Subcommittees]] = None
    systemCode: str
    url: str


class CommitteeResponse(BaseModel):
    committees: List[Committee]