from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar, Dict
import uuid
from neo4j import AsyncSession as Neo4jSession
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


# ── Shared contract ────────────────────────────────────────────────────────────

class AbstractRepository(ABC, Generic[T]):
    """Minimal interface every repository must satisfy."""

    @abstractmethod
    async def get_table(self, **filters) -> Sequence[T]:
        """Return rows / nodes from the underlying store."""
        ...

    @abstractmethod
    async def get_by_id(self, record_id: Any) -> T | None:
        ...

    @abstractmethod
    async def create(self, data: dict[str, Any]) -> T:
        ...

    @abstractmethod
    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def delete(self, record_id: Any) -> bool:
        ...


# ── PostgreSQL base repo ───────────────────────────────────────────────────────

class PostgresRepository(AbstractRepository[T]):
    """
    Concrete base for PostgreSQL repositories.

    Subclass and set `table_name` (and optionally override methods)
    to get a working repository with minimal boilerplate.
    """

    table_name: str = ""  # override in subclass

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_table(self, limit: int = 100, offset: int = 0, **filters) -> Sequence[Any]:
        """
        Fetch all rows from `table_name`, with optional key=value filters.
        Replace with SQLAlchemy ORM / select() calls in your subclass.
        """
        where_clause = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if filters:
            conditions = " AND ".join(f"{k} = :{k}" for k in filters)
            where_clause = f"WHERE {conditions}"
            params.update(filters)

        query = text(
            f"SELECT * FROM {self.table_name} {where_clause} "
            f"LIMIT :limit OFFSET :offset"
        )
        result = await self._session.execute(query, params)
        return result.mappings().all()

    async def get_by_id(self, record_id: Any) -> Any | None:
        query = text(f"SELECT * FROM {self.table_name} WHERE id = :id")
        result = await self._session.execute(query, {"id": record_id})
        return result.mappings().first()

    async def create(self, data: dict[str, Any]) -> Any:
        columns = ", ".join(data.keys())
        values = ", ".join(f":{k}" for k in data.keys())
        query = text(
            f"INSERT INTO {self.table_name} ({columns}) VALUES ({values}) RETURNING *"
        )
        result = await self._session.execute(query, data)
        return result.mappings().first()

    async def update(self, record_id: Any, data: dict[str, Any]) -> Any | None:
        set_clause = ", ".join(f"{k} = :{k}" for k in data.keys())
        query = text(
            f"UPDATE {self.table_name} SET {set_clause} WHERE id = :id RETURNING *"
        )
        result = await self._session.execute(query, {**data, "id": record_id})
        return result.mappings().first()

    async def delete(self, record_id: Any) -> bool:
        query = text(f"DELETE FROM {self.table_name} WHERE id = :id")
        result = await self._session.execute(query, {"id": record_id})
        return result.rowcount > 0


# ── Neo4j base repo ────────────────────────────────────────────────────────────
