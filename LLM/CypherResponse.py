import re
from pydantic import BaseModel, field_validator

class CypherResponse(BaseModel):
    cypher: str
    params: dict

    @field_validator("cypher")
    def must_not_be_unsupported(cls, v):
        if v.strip() == "UNSUPPORTED_QUERY":
            raise ValueError("Query cannot be answered from the current schema.")
        
        # Look for keywords as standalone words (case-insensitive)
        forbidden = ["CREATE", "MERGE", "DELETE", "SET"]
        for kw in forbidden:
            # \b ensures we match 'SET' but not 'ASSET'
            if re.search(rf"\b{kw}\b", v, re.IGNORECASE):
                raise ValueError(f"Write operation '{kw}' is not permitted.")
        
        return v.strip()