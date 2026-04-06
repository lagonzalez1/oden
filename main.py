from contextlib import asynccontextmanager
from fastapi import FastAPI
from Config.settings import settings
from Database.postgres import postgres_db
from Database.neo4j import neo4j_db
from Router.api import api_router
from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of database connections."""
    await postgres_db.connect()
    await neo4j_db.connect()
    config = RabbitMQConfig(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        username=settings.RABBITMQ_USER,
        password=settings.RABBITMQ_PASSWORD,
        virtual_host=settings.RABBITMQ_VHOST
    )
    rabbitmq_client.config = config
    await rabbitmq_client.connect()
    # Declare the queues to use
    await rabbitmq_client.declare_queue("worker-1", durable=True)
    await rabbitmq_client.declare_queue("worker-2", durable=True)
    print("✓ All services connected: PostgreSQL, Neo4j, RabbitMQ")
    print(f"  - RabbitMQ queues declared: worker-1, worker-2")
    yield 
    await postgres_db.disconnect()
    await neo4j_db.disconnect()
    await rabbitmq_client.close()


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
