from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar

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
# ── Neo4j base repo ────────────────────────────────────────────────────────────

class Neo4jRepository(AbstractRepository[T]):
    """
    Concrete base for Neo4j repositories.

    Subclass and set `label` to the node label you are working with.
    """

    label: str = ""  # override in subclass e.g. "User"

    def __init__(self, session: Neo4jSession):
        self._session = session

    async def get_table(self, limit: int = 100, offset: int = 0, **filters) -> list[dict]:
        """Return all nodes of `label`, with optional property filters."""
        where_parts = " AND ".join(f"n.{k} = ${k}" for k in filters)
        where_clause = f"WHERE {where_parts}" if where_parts else ""

        cypher = (
            f"MATCH (n:{self.label}) {where_clause} "
            f"RETURN n SKIP $offset LIMIT $limit"
        )
        params = {"offset": offset, "limit": limit, **filters}
        result = await self._session.run(cypher, params)
        records = await result.data()
        return [r["n"] for r in records]

    async def get_by_id(self, record_id: Any) -> dict | None:
        cypher = f"MATCH (n:{self.label}) WHERE elementId(n) = $id RETURN n"
        result = await self._session.run(cypher, {"id": record_id})
        record = await result.single()
        return record["n"] if record else None

    async def create(self, data: dict[str, Any]) -> dict:
        cypher = f"CREATE (n:{self.label} $props) RETURN n"
        result = await self._session.run(cypher, {"props": data})
        record = await result.single()
        return record["n"]

    async def update(self, record_id: Any, data: dict[str, Any]) -> dict | None:
        cypher = (
            f"MATCH (n:{self.label}) WHERE elementId(n) = $id "
            f"SET n += $props RETURN n"
        )
        result = await self._session.run(cypher, {"id": record_id, "props": data})
        record = await result.single()
        return record["n"] if record else None

    async def delete(self, record_id: Any) -> bool:
        cypher = f"MATCH (n:{self.label}) WHERE elementId(n) = $id DETACH DELETE n"
        result = await self._session.run(cypher, {"id": record_id})
        summary = await result.consume()
        return summary.counters.nodes_deleted > 0
