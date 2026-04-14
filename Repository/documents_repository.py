from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar
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
    schema_name: str = ""
    pk_name: str = "id"

    def __init__(self, session: AsyncSession):
        self._session = session
    
    @property
    def full_table_name(self) -> str:
        """Returns the escaped full path: "schema"."table" """
        return f'{self.schema_name}.{self.table_name}'


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
            f"SELECT * FROM {self.full_table_name} {where_clause} "
            f"LIMIT :limit OFFSET :offset"
        )
        result = await self._session.execute(query, params)
        return result.mappings().all()

    async def get_by_id(self, record_id: Any) -> Any | None:
        query = text(f"SELECT * FROM {self.full_table_name} WHERE {self.pk_name} = :id")
        result = await self._session.execute(query, {"id": record_id})
        return result.mappings().first()

    async def create(self, data: dict[str, Any]) -> Any:
        columns = ", ".join(data.keys())
        values = ", ".join(f":{k}" for k in data.keys())
        query = text(
            f"INSERT INTO {self.full_table_name} ({columns}) VALUES ({values}) RETURNING *"
        )
        print(self.full_table_name)
        result = await self._session.execute(query, data)
        return result.mappings().first()

    async def update(self, record_id: Any, data: dict[str, Any]) -> Any | None:
        set_clause = ", ".join(f"{k} = :{k}" for k in data.keys())
        query = text(
            f"UPDATE {self.full_table_name} SET {set_clause} WHERE {self.pk_name} = :id RETURNING *"
        )
        result = await self._session.execute(query, {**data, "id": record_id})
        return result.mappings().first()

    async def delete(self, record_id: Any) -> bool:
        query = text(f"DELETE FROM {self.full_table_name} WHERE {self.pk_name} = :id")
        result = await self._session.execute(query, {"id": record_id})
        return result.rowcount > 0

# ── PostgreSQL base repo ───────────────────────────────────────────────────────

class DocumentRepository(PostgresRepository):
    """
    Repository for the 'documents' table. 
    Overrides ID-specific methods to use 'doc_id' instead of 'id'.
    Just override the specific schema_names, tables ... and use the abstract classess above
    This section is for specialized queries and complex queries.
    """
    table_name = "documents"
    schema_name = "oden"
    pk_name = "doc_id"
    
    async def get_by_year(self, year: int):
        query = text(f"SELECT * FROM {self.full_table_name} WHERE filing_year = :year")
        result = await self._session.execute(query, {"year": year})
        return result.mappings().all()