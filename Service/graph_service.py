import csv
import io
import json
from datetime import datetime
from typing import Any
from fastapi import UploadFile
from Repository.graph_repository import AbstractRepository
from typing import Any, Generic, Sequence, TypeVar
from MessageBroker.rabbitmq_client import rabbitmq_client

T = TypeVar("T")


class BaseService(Generic[T]):
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, repository: AbstractRepository[T]):
        self._repo = repository

    # ── Read ──────────────────────────────────────────────────────────────────


    # ── Write ─────────────────────────────────────────────────────────────────

    

    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        return await self._repo.update(record_id, data)

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self._repo.delete(record_id)
