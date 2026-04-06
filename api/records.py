"""
Example endpoints — swap `BaseService` / `PostgresRepository` for your
domain-specific service and repo when you extend the project.
"""
from typing import Any
from fastapi import APIRouter, HTTPException, Query, status, UploadFile, File
from Core.dependencies import Neo4jDep, PostgresDep
from Repository.documents_repository import DocumentRepository
from MessageBroker import rabbitmq_client
from Repository.graph_repository import Neo4jRepository
from Service.document_service import BaseService
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _postgres_service(session: Any, table: str, schema_name: str, pk_name: str) -> DocumentRepository:
    repo = DocumentRepository(session)
    repo.table_name = table
    repo.schema_name = schema_name
    repo.pk_name = pk_name
    return repo


def _neo4j_service(session: Any, label: str) -> Neo4jRepository:
    repo = Neo4jRepository(session)
    repo.label = label
    return repo

# ── PostgreSQL example routes ─────────────────────────────────────────────────

doc_router = APIRouter(prefix="/documents", tags=["Documents"])

@doc_router.get("/data", summary="Scan all rows in the documents table")
async def scan_documents(
    session: PostgresDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    # Optional: allow filtering by specific fields
    filing_year: int | None = None,
    state_dst: str | None = None
):
    """
    Performs a scan of the documents table with optional pagination and filtering.
    """
    repo = _postgres_service(session, "oden", "documents", "doc_id")
    
    # Prepare filters for the get_table method
    filters = {}
    if filing_year:
        filters["filing_year"] = filing_year
    if state_dst:
        filters["state_dst"] = state_dst

    # get_table is inherited from your PostgresRepository
    rows = await repo.get_table(limit=224, offset=1, **filters)
    
    return {
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": rows
    }


@doc_router.post("/upload-csv", status_code=status.HTTP_201_CREATED)
async def upload_documents_csv(
    session: PostgresDep,
    file: UploadFile = File(...)
):
    """ Upload a CSV file to populate the documents table. """
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file extension. Please upload a .csv file."
        )
    repo = _postgres_service(session, "oden", "documents", "doc_id")
    service = BaseService(repo)
    try:
        count = await service.process_document_csv(file)
        return {
            "message": "CSV processed successfully",
            "rows_inserted": count,
            "filename": file.filename
        }
    except Exception as e:
        # In a real app, you'd log this error
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing CSV: {str(e)}"
        )



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

router.include_router(doc_router)
router.include_router(neo4j_router)
