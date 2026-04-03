"""
Example endpoints — swap `BaseService` / `PostgresRepository` for your
domain-specific service and repo when you extend the project.
"""
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from Core.dependencies import Neo4jDep, PostgresDep
from Repository.base_repository import Neo4jRepository, PostgresRepository
from Service.base_service import BaseService

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _postgres_service(session: Any, table: str) -> BaseService:
    repo = PostgresRepository(session)
    repo.table_name = table
    return BaseService(repo)


def _neo4j_service(session: Any, label: str) -> BaseService:
    repo = Neo4jRepository(session)
    repo.label = label
    return BaseService(repo)


# ── PostgreSQL example routes ─────────────────────────────────────────────────

pg_router = APIRouter(prefix="/postgres/{table}", tags=["PostgreSQL"])


@pg_router.get("/", summary="List all rows from a table")
async def list_rows(
    table: str,
    session: PostgresDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    svc = _postgres_service(session, table)
    return await svc.list(limit=limit, offset=offset)


@pg_router.get("/{record_id}", summary="Get a single row by ID")
async def get_row(table: str, record_id: str, session: PostgresDep):
    svc = _postgres_service(session, table)
    record = await svc.get(record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return record


@pg_router.post("/", status_code=status.HTTP_201_CREATED, summary="Insert a row")
async def create_row(table: str, payload: dict[str, Any], session: PostgresDep):
    svc = _postgres_service(session, table)
    return await svc.create(payload)


@pg_router.put("/{record_id}", summary="Update a row")
async def update_row(table: str, record_id: str, payload: dict[str, Any], session: PostgresDep):
    svc = _postgres_service(session, table)
    record = await svc.update(record_id, payload)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return record


@pg_router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a row")
async def delete_row(table: str, record_id: str, session: PostgresDep):
    svc = _postgres_service(session, table)
    deleted = await svc.delete(record_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")


# ── Neo4j example routes ──────────────────────────────────────────────────────

neo4j_router = APIRouter(prefix="/neo4j/{label}", tags=["Neo4j"])


@neo4j_router.get("/", summary="List all nodes with a given label")
async def list_nodes(
    label: str,
    session: Neo4jDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    svc = _neo4j_service(session, label)
    return await svc.list(limit=limit, offset=offset)


@neo4j_router.get("/{node_id}", summary="Get a node by element ID")
async def get_node(label: str, node_id: str, session: Neo4jDep):
    svc = _neo4j_service(session, label)
    node = await svc.get(node_id)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return node


@neo4j_router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a node")
async def create_node(label: str, payload: dict[str, Any], session: Neo4jDep):
    svc = _neo4j_service(session, label)
    return await svc.create(payload)


@neo4j_router.put("/{node_id}", summary="Update a node")
async def update_node(label: str, node_id: str, payload: dict[str, Any], session: Neo4jDep):
    svc = _neo4j_service(session, label)
    node = await svc.update(node_id, payload)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return node


@neo4j_router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a node")
async def delete_node(label: str, node_id: str, session: Neo4jDep):
    svc = _neo4j_service(session, label)
    deleted = await svc.delete(node_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")


# ── Collect both routers ──────────────────────────────────────────────────────

router.include_router(pg_router)
router.include_router(neo4j_router)
