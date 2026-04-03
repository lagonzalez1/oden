from typing import Any, Generic, Sequence, TypeVar

from Repository.base_repository import AbstractRepository

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

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        **filters,
    ) -> Sequence[T]:
        """Return a page of records, optionally filtered."""
        return await self._repo.get_table(limit=limit, offset=offset, **filters)

    async def get(self, record_id: Any) -> T | None:
        """Return a single record by ID, or None if not found."""
        return await self._repo.get_by_id(record_id)

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, data: dict[str, Any]) -> T:
        """Create and return a new record."""
        return await self._repo.create(data)

    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        return await self._repo.update(record_id, data)

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self._repo.delete(record_id)
