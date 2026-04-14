from typing import AsyncGenerator
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from Config.settings import settings


class Neo4jDatabase:
    def __init__(self):
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        # Verify connectivity on startup
        await self._driver.verify_connectivity()

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if not self._driver:
            raise RuntimeError("Neo4j not connected. Call connect() first.")
        async with self._driver.session() as session:
            yield session


neo4j_db = Neo4jDatabase()
