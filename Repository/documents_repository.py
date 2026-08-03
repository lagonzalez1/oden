from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar, Dict, List, Optional
from sqlalchemy import text
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    async def get_by_col(self, col: str, col_val: str)->T | None:
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
    
    @abstractmethod
    async def upsert(self, data: dict[str, Any], conflict_column: str) -> bool:
        ...


# ── PostgreSQL base repo ───────────────────────────────────────────────────────

class PostgresRepository(AbstractRepository[T]):
    """
    Concrete base for PostgreSQL repositories.

    Subclass and set `table_name` (and optionally override methods)
    to get a working repository with minimal boilerplate.
    """
    table_name: str = "documents" 
    schema_name: str = "oden"
    pk_name: str = "doc_id"

    def __init__(self, session: AsyncSession):
        self._session = session
    
    @property
    def full_table_name(self) -> str:
        """Returns the escaped full path: "schema"."table" """
        return f'{self.schema_name}.{self.table_name}'

    @asynccontextmanager 
    async def transaction(self):
        """ Get a transaction based on current session. """
        try:
            yield self._session
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        finally:
            await self._session.close()


    async def get_table(self, limit: int = 200, offset: int = 0, filters: Dict = {}) -> Sequence[Any]:
        """
        Fetch all rows from `table_name`, with optional key=value filters.
        Replace with SQLAlchemy ORM / select() calls in your subclass.
        """
        where_clause = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if filters:
            conditions = " AND ".join(f"{k} = :{k}" for k, v in filters.items())
            where_clause = f"WHERE {conditions}"
            params.update(filters)

        query = text(
            f"SELECT * FROM {self.full_table_name} {where_clause} "
            f"LIMIT :limit OFFSET :offset"
        )
        print(query)
        result = await self._session.execute(query, params)
        return result.mappings().all()

    async def get_by_col(self, col: str, col_val: str) ->Any | None:
        query = text(f"SELECT * FROM {self.full_table_name} WHERE {col} = :id")
        result = await self._session.execute(query, {"id": col_val})
        return result.mappings().first()


    async def get_by_id(self, record_id: Any) -> Any | None:
        query = text(f"SELECT * FROM {self.full_table_name} WHERE {self.pk_name} = :id")
        result = await self._session.execute(query, {"id": record_id})
        return result.mappings().first()

    async def get_by_ids(self, ids: List[Any]) -> Any | None:
        query = text(f"SELECT * FROM {self.full_table_name} WHERE {self.pk_name} = ANY(:ids)")
        results = await self._session.execute(query, {"ids": ids})
        return results.mappings().all()

    async def create(self, data: dict[str, Any]) -> Any:
        try:
            columns = ", ".join(data.keys())
            values = ", ".join(f":{k}" for k in data.keys())
            query = text(
                f"INSERT INTO {self.full_table_name} ({columns}) VALUES ({values}) ON CONFLICT ({self.pk_name}) DO NOTHING RETURNING *"
            )
            result = await self._session.execute(query, data)
            return result.mappings().first()
        except sqlalchemy.exc.InvalidRequestError as e:
            logger.error(f"[DocumentRepository Error] error: {e}")
            raise e
        except sqlalchemy.exc.ArgumentError as e:
            logger.error(f"[DocumentRepository Error] error: {e}")
            raise e


    async def update(self, record_id: str, data: Dict[str, Any]) -> Any | None:
        try:
            set_clause = ", ".join(f"{k} = :{k}" for k in data.keys())
            query = text(
                f"UPDATE {self.full_table_name} SET {set_clause} WHERE {self.pk_name} = :id RETURNING *"
            )
            params = {**data, "id": record_id}
            result = await self._session.execute(query, params)
            return result.mappings().first()
        except sqlalchemy.exc.InvalidRequestError as e:
            logger.error(f"[DocumentRepository Error] error: {e}")
            raise e
        except sqlalchemy.exc.ArgumentError as e:
            logger.error(f"[DocumentRepository Error] error: {e}")
            raise e
        
    async def update_embedding(self, committee_id: str, embedding: list[float]) -> Any | None:
        """Store a computed embedding vector for a committee."""
        try:
            query = text(f"""
                UPDATE {self.full_table_name}
                SET embedding = :embedding::vector
                WHERE {self.pk_name} = :id
                RETURNING *
            """)
            result = await self._session.execute(query, {
                "embedding": json.dumps(embedding),
                "id": committee_id,
            })
            return result.mappings().first()
        except sqlalchemy.exc.InvalidRequestError as e:
            logger.error(f"[Committee] update_embedding error: {e}")
            raise

    async def upsert(self, data: dict[str, Any], conflict_column: str) -> Any:
        """
        Insert a row or update on conflict.
        Unlike create() which returns None on conflict, this always returns the row.
        """
        try:
            columns = ", ".join(data.keys())
            values  = ", ".join(f":{k}" for k in data.keys())

            # Exclude the conflict column from the update clause
            # — we don't want to overwrite the PK/unique key itself
            update_clause = ", ".join(
                f"{k} = EXCLUDED.{k}"
                for k in data.keys()
                if k != conflict_column
            )
            query = text(f"""
                INSERT INTO {self.full_table_name} ({columns})
                VALUES ({values})
                ON CONFLICT ({conflict_column})
                DO UPDATE SET {update_clause}
                RETURNING *
            """)

            result = await self._session.execute(query, data)
            return result.mappings().first()
        except sqlalchemy.exc.InvalidRequestError as e:
            logger.error(f"[{self.table_name}] upsert InvalidRequestError: {e}")
            raise
        except sqlalchemy.exc.ArgumentError as e:
            logger.error(f"[{self.table_name}] upsert ArgumentError: {e}")
            raise

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

   

