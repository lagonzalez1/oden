from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from Config.settings import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


class PostgresDatabase:
    def __init__(self):
        self._engine = None
        self._session_factory = None

    async def connect(self) -> None:
        self._engine = create_async_engine(
            settings.POSTGRES_DSN,
            echo=settings.DEBUG,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    async def disconnect(self) -> None:
        if self._engine:
            await self._engine.dispose()

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if not self._session_factory:
            raise RuntimeError("Database not connected. Call connect() first.")
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


postgres_db = PostgresDatabase()
