from dataclasses import dataclass
from typing import Any, Optional, Dict, List

@dataclass
class EdgeDTO:
    id: str
    source: str
    target: str
    type: str
    data: Optional[Dict[str, Any]] = None

@dataclass
class NodeDTO:
    id: str
    type: str
    data: dict[str, Any]


@dataclass
class GraphDTO:
    nodes: List[NodeDTO]
    edges: List[EdgeDTO]

def neo4j_to_dict(obj) -> Dict[str, Any]:
    """Safely convert Neo4j Node or Relationship to dict"""
    if obj is None:
        return {}
    
    # If it's already a dict
    if isinstance(obj, dict):
        return obj
    
    # If it has items() method (Node, Relationship)
    if hasattr(obj, 'items'):
        return dict(obj.items())
    
    # If it has keys() and __getitem__ (dict-like)
    if hasattr(obj, 'keys') and hasattr(obj, '__getitem__'):
        return {key: obj[key] for key in obj.keys()}
    
    # Try direct conversion
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return {}