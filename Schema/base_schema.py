from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class AppBaseModel(BaseModel):
    """Shared Pydantic config for all schemas."""
    model_config = ConfigDict(
        from_attributes=True,       # allows ORM model -> schema
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# Document schemas ─────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    year: Optional[str] = None

class UpdateData(BaseModel):
    doc_id_parsed: Optional[bool] = None
    doc_size: Optional[int] = None

class DocumentUpdateRequest(BaseModel):
    doc_id: str
    update_data: Optional[UpdateData] = None
    # Optional: validation
    @field_validator('doc_id')
    @classmethod
    def validate_doc_id(cls, v):
        return f"{v}" 



# ── Generic record schemas ─────────────────────────────────────────────────────

class RecordBase(AppBaseModel):
    """Fields shared across create / update / read."""
    pass


class RecordCreate(RecordBase):
    """Payload accepted when creating a record."""
    pass


class RecordUpdate(RecordBase):
    """Payload accepted when updating a record (all fields optional)."""
    pass


class RecordRead(RecordBase):
    """Shape returned to callers — extend with your real fields."""
    id: UUID | int
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Pagination ─────────────────────────────────────────────────────────────────

class PaginatedResponse(AppBaseModel):
    total: int
    page: int
    page_size: int
    items: list[Any]
