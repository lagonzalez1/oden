from pydantic import BaseModel, field_validator

class CypherResponse(BaseModel):
    cypher: str
    params: dict

    @field_validator("cypher")
    def must_not_be_unsupported(cls, v):
        if v.strip() == "UNSUPPORTED_QUERY":
            raise ValueError("Query cannot be answered from the current schema.")
        if any(kw in v.upper() for kw in ["CREATE", "MERGE", "DELETE", "SET"]):
            raise ValueError("Write operations are not permitted in query output.")
        return v.strip()