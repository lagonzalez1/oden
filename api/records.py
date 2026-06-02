"""
Example endpoints — swap `BaseService` / `PostgresRepository` for your
domain-specific service and repo when you extend the project.
"""
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, status, UploadFile, File
from Core.dependencies import Neo4jDep, UoWDep, PostgresDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import Neo4jRepository, CommitteeRepository, TransactionRepository
from Service.document_service import DocumentsService
from Service.stock_gain_service import StockGainsService
from Service.commitee_service import CommitteeService
from Service.graph_service import GraphService
from Schema.base_schema import DocumentUpdateRequest, IngestRequest, MonitorChangesRequest, GetAssociatedTransactions
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


def _neo4j_service(session: Any, label: str, repo_type: str = "base") -> Neo4jRepository:
    """Factory that returns the appropriate repository subclass."""
    
    repos = {
        "base": Neo4jRepository,
        "committee": CommitteeRepository,
        "transaction": TransactionRepository,
    }
    
    repo_class = repos.get(repo_type, Neo4jRepository)
    repo = repo_class(session)  # ← Creates instance of the correct class
    repo.label = label
    return repo



# ── PostgreSQL example routes ─────────────────────────────────────────────────

doc_router = APIRouter(prefix="/documents", tags=["Documents"])


@doc_router.get("/health_check", summary="Scan all rows in the documents table", status_code=status.HTTP_200_OK)
async def health_check():
    """ Performs a health_check . """
    return {
        "Status": 'OK'
    }


@doc_router.post("/upload_csv", status_code=status.HTTP_201_CREATED)
async def upload_documents_csv(
    uow: UoWDep,
    file: UploadFile = File(...)
):
    """ Upload a CSV file to populate the documents table. """
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file extension. Please upload a .csv file."
        )
    service = DocumentsService(uow)
    try:
        count = await service.process_document_csv(file=file)
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


@doc_router.get("/ingest_commitees", summary="Find committee info.", status_code=status.HTTP_201_CREATED)
async def ingest_committees(
    uow: UoWDep,
):
    """ Get unprocesses documents, simple Boolean check for now, but in the future date check will work best. """
    service = CommitteeService(uow)
    count = await service.ingest_committee_data()
    
    return {
        "update": count
    }

@doc_router.post("/ingest_documents", summary="Check unprocessesed doc_ids, send to queue to process.", status_code=status.HTTP_201_CREATED)
async def ingest_documents(
    uow: UoWDep,
    request: IngestRequest
):
    """ Get unprocesses documents, simple Boolean check for now, but in the future date check will work best. """
    service = DocumentsService(uow)
    count = await service.ingest_documents(year=request.year)
    return {
        "messages_in_queue": count,
    }


@doc_router.post("/ingest_legislators", summary="Check unprocessesed doc_ids, send to queue to process.", status_code=status.HTTP_201_CREATED)
async def ingest_legislators(
    uow: UoWDep,
):
    """ Fetch legislators from wiki page using Custom class, upsert linkage from committee_ to member_. """
    service = DocumentsService(uow)
    cnt = await service.upsert_legislator_from_wiki()
    return {
        "processed": cnt,
    }

@doc_router.post("/monitor_changes", summary="Monitor changes in your db", status_code=status.HTTP_201_CREATED)
async def doc_id_check(
    uow: UoWDep,
    request: MonitorChangesRequest
):
    """ Get unprocesses documents, simple Boolean check for now, but in the future date check will work best. """
    service = DocumentsService(uow)
    count = await service.process_unprocessed_documents(year=int(request.year))
    return {
        "messages_in_queue": count,
    }

@doc_router.post("/natural_language_query", status_code=status.HTTP_201_CREATED)
async def natural_language_query(
    uow: UoWDep,
    question: str = None
):
    """ Natural language query, sends message to queue. """
    service = DocumentsService(uow)
    try:
        response = await service.natural_language_query(question)
        return { 'response': response }
    except Exception as e:
        # In a real app, you'd log this error
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing CSV: {str(e)}"
        )

@doc_router.post("/get_associated_transactions")
async def upload_documents_csv(
    uow: UoWDep,
    request: GetAssociatedTransactions
):
    """ Natural language query, sends message to queue. """
    service = StockGainsService(uow)
    try:
        response = await service.get_associated_transactions(request)
        return { 'response': response }
    except Exception as e:
        # In a real app, you'd log this error
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing: {str(e)}"
        )

@doc_router.get("/get_clients")
async def get_clients(
    uow: UoWDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """ Natural language query, sends message to queue. """
    service = StockGainsService(uow)
    try:
        response = await service.get_clients()
        return { 'response': response }
    except Exception as e:
        # In a real app, you'd log this error
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing CSV: {str(e)}"
        )

@doc_router.get("/get_client_performance")
async def get_client_performance(
    uow: UoWDep,
    filer_name: str = Query(..., description="Name of the filer"),
):
    """ Natural language query, sends message to queue. """
    service = StockGainsService(uow)
    try:
        response = await service.get_client_performance(filer_name)
        return { 'response': response }
    except Exception as e:
        # In a real app, you'd log this error
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing CSV: {str(e)}"
        )


# ── Neo4j example routes ──────────────────────────────────────────────────────

neo4j_router = APIRouter(prefix="/graph", tags=["Neo4j"])


@neo4j_router.get("/sync", summary="List all nodes with a given label")
async def sync(
    session: Neo4jDep,
    uow: UoWDep,
):
    graph_base = _neo4j_service(session, "Committee", "base")
    graph_base_committee = _neo4j_service(session, "Committee", "committee")
    service = CommitteeService(uow)
    graph_service = GraphService(graph_base)
    graph_service_com = GraphService(graph_base_committee)


    committees = await service.get_committees()
    committees_rel = await service.get_committees_relationships()
    if committees:
        cnt = await graph_service.create_committee(committees)
        cnt_members = await graph_service_com.merge_committee_member(committees_rel)

    return {
        "committees": cnt,
        "committee_members": cnt_members
    }



@neo4j_router.get("/sync_house", summary="List all nodes with a given label")
async def sync_house(
    session: Neo4jDep,
    uow: UoWDep,
):
    graph_base = _neo4j_service(session, "Committee", "base")
    graph_base_committee = _neo4j_service(session, "Committee", "committee")
    service = CommitteeService(uow)
    graph_service = GraphService(graph_base)
    graph_service_com = GraphService(graph_base_committee)


    committees = await service.get_committees({"chamber": "house"})
    committees_rel = await service.get_committees_relationships(chamber='house')
    if committees:
        cnt = await graph_service.create_committee(committees)
        cnt_members = await graph_service_com.merge_committee_member(committees_rel)

    return {
        "committees": cnt,
        "committee_members": cnt_members
    }


@neo4j_router.get("/legislators")
async def get_legislators(
    session: Neo4jDep,
    label: str = Query(...),
    node_id: Optional[str] = Query(None),
    first_name: Optional[str] = Query(None),
    last_name: Optional[str] = Query(None),
):
    graph_base = _neo4j_service(
        session,
        label=label,
        repo_type="base"
    )
    graph_service = GraphService(graph_base)
    if node_id:
        return await graph_service.get_node_by_id(node_id)
    return await graph_service.search(
        first_name=first_name,
        last_name=last_name
    )



@neo4j_router.get("/node")
async def get_node(
    session: Neo4jDep,
    node_id: Optional[str] = Query(None),
):
    graph_base = _neo4j_service(
        session,
        label="",
        repo_type="base"
    )
    graph_service = GraphService(graph_base)
    if node_id:
        node = await graph_service.get_node_by_id(node_id)
        return node
    





# ── Collect both routers ──────────────────────────────────────────────────────

router.include_router(doc_router)
router.include_router(neo4j_router)
