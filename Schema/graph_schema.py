from dataclasses import dataclass
from typing import Any


@dataclass
class EdgeDTO:
    id: str
    source: str
    target: str
    type: str
    data: dict | None = None

@dataclass
class NodeDTO:
    id: str
    type: str
    data: dict[str, Any]


@dataclass
class GraphDTO:
    nodes: list[NodeDTO]
    edges: list[EdgeDTO]

