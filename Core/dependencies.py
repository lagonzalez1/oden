from typing import Annotated, AsyncGenerator

from fastapi import Depends
from neo4j import AsyncSession as Neo4jSession
from sqlalchemy.ext.asyncio import AsyncSession
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork
from Database.neo4j_ import neo4j_db
from Database.postgres import postgres_db
from Core.unit_of_work import AbstractUnitOfWork


# ── PostgreSQL ────────────────────────────────────────────────────────────────

async def get_postgres_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session."""
    async for session in postgres_db.get_session():
        yield session


PostgresDep = Annotated[AsyncSession, Depends(get_postgres_session)]


async def get_uow(session: PostgresDep) -> AsyncGenerator[SqlAlchemyUnitOfWork, None]:
    """Provides a Unit of Work to the FastAPI route."""
    yield SqlAlchemyUnitOfWork(session)

# Define a clean type alias for your routes
UoWDep = Annotated[AbstractUnitOfWork, Depends(get_uow)]


# ── Neo4j ─────────────────────────────────────────────────────────────────────

async def get_neo4j_session() -> AsyncGenerator[Neo4jSession, None]:
    """Yield an async Neo4j session."""
    async for session in neo4j_db.get_session():
        yield session


Neo4jDep = Annotated[Neo4jSession, Depends(get_neo4j_session)]
