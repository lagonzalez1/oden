from contextlib import asynccontextmanager

from fastapi import FastAPI

from Config.settings import settings
from Database.postgres import postgres_db
from Database.neo4j import neo4j_db
from Router.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of database connections."""
    await postgres_db.connect()
    await neo4j_db.connect()
    yield
    await postgres_db.disconnect()
    await neo4j_db.disconnect()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="FastAPI service with PostgreSQL and Neo4j",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }
