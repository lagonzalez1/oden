from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar, Dict, List
from sqlalchemy import text
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import logging

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
            conditions = " AND ".join(f"{k} = {v}" for k, v in filters.items())
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



class StockRepository(PostgresRepository):
    table_name = "stock_gains"
    schema_name = "oden"
    pk_name = "id"

    async def get_distinct_clients(self):
        query = text(f"SELECT DISTINCT filer_name FROM {self.full_table_name}")
        result = await self._session.execute(query)
        return result.mappings().all()

    async def get_by_doc_id(
        self,
        doc_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Any]:
        query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE doc_id = :doc_id
            ORDER BY trade_date DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self._session.execute(query, {
            "doc_id": doc_id,
            "limit":  limit,
            "offset": offset
        })
        return result.mappings().all()

    async def get_by_name(
        self,
        filer_name: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Any]:
        query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE filer_name ILIKE :filer_name
            ORDER BY trade_date DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self._session.execute(query, {
            "filer_name": f"%{filer_name}%",
            "limit":      limit,
            "offset":     offset
        })
        return result.mappings().all()
    

class CommitteeRepository(PostgresRepository):
    table_name = "committee_membership"
    schema_name = "oden"
    pk_name = "id"

    async def get_committee_membership(self):
        query = text(f""" 
            select l.first_name, l.last_name, l.bioguide_id, l.chamber, 
            l.leadership_role, l.party, l.state, cm.committee_id ,com.title, com.is_subcommittee, cm.role
            from oden.committee_membership cm
            left join oden.committee com on cm.committee_id = com.id
            left join oden.legislator l on l.id = cm.legislator_id;        
        """)
        result = await self._session.execute(query)
        return result.mappings().all()

    