"""
Example endpoints — swap `BaseService` / `PostgresRepository` for your
domain-specific service and repo when you extend the project.
"""
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, Body, status, UploadFile, File, Depends, Request
from Core.dependencies import Neo4jDep, UoWDep, PostgresDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import Neo4jRepository, CommitteeRepository, TransactionRepository
from Service.document_service import DocumentsService
from Service.stock_gain_service import StockGainsService
from Service.commitee_service import CommitteeService
from Service.graph_service import GraphService
from Schema.base_schema import CommitteeEmbeddings, IngestRequest, MonitorChangesRequest, GetAssociatedTransactions, CreateCommitteeRequest
from Schema.graph_schema import GraphDTO
from Schema.graph_search_schema import GraphSearchParams, LOOKUP_TYPE_OPTIONS
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



@doc_router.get("/ingest_commitees", summary="Find committee info.", status_code=status.HTTP_201_CREATED)
async def ingest_committees(
    uow: UoWDep,
):
    """ Create committees based senate committee from xml. """
    service = CommitteeService(uow)
    count = await service.ingest_committee_data()
    
    return {
        "update": count
    }


@doc_router.post("/ingest_commitees", summary="Ingest committees from GitHub congress-legislators", status_code=status.HTTP_201_CREATED)
async def ingest_commitees_github(
    uow: UoWDep,
):
    """ 
    Ingest all committees and subcommittees from GitHub's congress-legislators repository.
    Returns counts of committees and subcommittees inserted.
    """
    service = CommitteeService(uow)
    result = await service.ingest_committee_data_from_github()
    
    return {
        "committees_inserted": result["committees"],
        "subcommittees_inserted": result["subcommittees"],
        "total": result["committees"] + result["subcommittees"]
    }


@doc_router.post("/ingest_legislators", summary="Ingest legislators from GitHub congress-legislators", status_code=status.HTTP_201_CREATED)
async def ingest_legislators_github(
    uow: UoWDep,
):
    """ 
    Ingest all current legislators from GitHub's congress-legislators repository.
    
    Sources: 
    - https://unitedstates.github.io/congress-legislators/legislators-current.json
    - https://unitedstates.github.io/congress-legislators/legislators-social-media.json
    
    Populates all legislator fields including Twitter handles, leadership roles, terms history (JSONB).
    Returns counts of legislators inserted (active vs inactive, with Twitter handles).
    Does NOT create committee memberships (handled separately).
    """
    service = CommitteeService(uow)
    result = await service.ingest_legislators_from_github()
    
    return {
        "legislators_inserted": result["legislators"],
        "active": result["active"],
        "inactive": result["inactive"],
        "with_twitter": result["with_twitter"]
    }


@doc_router.post("/ingest_committee_memberships", summary="Ingest committee memberships from GitHub", status_code=status.HTTP_201_CREATED)
async def ingest_committee_memberships_github(
    uow: UoWDep,
):
    """ 
    Ingest all committee memberships from GitHub's congress-legislators repository.
    
    Source: https://unitedstates.github.io/congress-legislators/committee-membership-current.json
    
    Links legislators to committees based on bioguide_id and committee_thomas_id.
    
    Prerequisites:
    - Run /ingest_legislators first (to populate legislators)
    - Run /ingest_commitees_github first (to populate committees)
    
    Returns counts of memberships inserted and any skipped due to missing references.
    """
    service = CommitteeService(uow)
    result = await service.ingest_committee_memberships_from_github()
    
    return {
        "memberships_inserted": result["memberships"],
        "skipped": result["skipped"],
        "committees_processed": result["committees"]
    }

@doc_router.post("/ingest_documents", summary="Check unprocessesed doc_ids, send to queue to process.", status_code=status.HTTP_201_CREATED)
async def ingest_documents(
    uow: UoWDep,
    request: IngestRequest
):
    """ Get unprocesses documents, simple Boolean check for now, but in the future date check will work best. """
    service = DocumentsService(uow)
    count = await service.ingest_documents(year=request.year, count=request.count)
    return {
        "messages_in_queue": count,
    }


@doc_router.patch("/embeddings", summary="Check unprocessesed doc_ids, send to queue to process.", status_code=status.HTTP_201_CREATED)
async def embeddings(
    uow: UoWDep,

):
    """ Create house committee with members from wiki page, upsert into db. """
    service = CommitteeService(uow)
    cnt = await service.create_committee_embeddings()
    return {
        "update_count": cnt,
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
    question: str = Body(..., embed=True, description="Natural language question"),
):
    """Natural language query — persists row and enqueues worker-2."""
    if not question or not question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="question is required",
        )
    service = DocumentsService(uow)
    try:
        response = await service.natural_language_query(question.strip())
        return {"response": response}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing natural language query: {str(e)}",
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


@neo4j_router.get(
    "/natural_language_query/{query_id}/graph",
    summary="Execute a completed NL Cypher query and return GraphDTO",
    status_code=status.HTTP_200_OK,
)
async def execute_natural_language_query_graph(
    query_id: str,
    uow: UoWDep,
    session: Neo4jDep,
):
    """
    Load a completed natural_language_queries row (response=cypher, params=JSON)
    and execute it against Neo4j, returning nodes/edges as GraphDTO.
    """
    import json as _json

    doc_service = DocumentsService(uow)
    row = await doc_service.get_natural_language_query(query_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")

    status_value = (row.get("status") or "").lower()
    if status_value not in {"completed", "complete", "success"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Query is not ready (status={row.get('status')})",
        )

    cypher = row.get("response")
    if not cypher or not str(cypher).strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query has no Cypher response to execute",
        )

    raw_params = row.get("params")
    params: dict = {}
    if raw_params:
        if isinstance(raw_params, dict):
            params = raw_params
        else:
            try:
                params = _json.loads(raw_params)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Stored params are not valid JSON",
                )

    graph_base = _neo4j_service(session, label="", repo_type="base")
    graph_service = GraphService(graph_base)
    try:
        return await graph_service.run_cypher_to_graph(cypher=str(cypher), params=params)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute Cypher: {e}",
        )



@neo4j_router.patch("/sync_senate", summary="List all nodes with a given label")
async def sync(
    session: Neo4jDep,
    uow: UoWDep,
):
    graph_base = _neo4j_service(session, "Committee", "base")
    graph_base_committee = _neo4j_service(session, "Committee", "committee")
    service = CommitteeService(uow)
    graph_service = GraphService(graph_base)
    graph_service_com = GraphService(graph_base_committee)


    committees = await service.get_committees(filter={"chamber": "Senate"})
    committees_rel = await service.get_committees_relationships(chamber="Senate")
    if committees:
        cnt = await graph_service.create_committee(committees)
        cnt_members = await graph_service_com.merge_committee_member(committees_rel)

    return {
        "committees": cnt,
        "committee_members": cnt_members
    }



@neo4j_router.patch("/sync_house", summary="List all nodes with a given label")
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
        first_name=first_name.upper(),
        last_name=last_name.upper()
    )



@neo4j_router.get("/committees")
async def get_node(
    session: Neo4jDep,
    committee: Optional[str] = Query(None),
    
):
    graph_base = _neo4j_service(
        session,
        label="",
        repo_type="base"
    )
    graph_service = GraphService(graph_base)
    if committee:
        committees = await graph_service.get_committees(committee=committee)
        return committees
        


def graph_search_params(request: Request) -> GraphSearchParams:
    return GraphSearchParams(**request.query_params)

@neo4j_router.get("/search")
async def search_node(
    session: Neo4jDep,
    search_params: GraphSearchParams = Depends(graph_search_params),
):
    """
    Filter lookup by node label. Query params mirror frontend buildSearchParams.
    Supported labels: Asset, Committee, Issuer, Member, Transaction.
    """
    if search_params.label not in LOOKUP_TYPE_OPTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported label '{search_params.label}'. Expected one of {LOOKUP_TYPE_OPTIONS}",
        )

    graph_base = _neo4j_service(
        session,
        label=search_params.label,
        repo_type="base",
    )
    graph_service = GraphService(graph_base)
    return await graph_service.search(
        filters=search_params.to_repo_filters(),
    )



@neo4j_router.get("/node")
async def get_node(
    session: Neo4jDep,
    node_id: Optional[str] = Query(None, description="Member elementId or bioguide_id"),
    depth: int = Query(
        2,
        ge=1,
        le=2,
        description="1=committees+transactions; 2=also assets, derivatives, issuers",
    ),
    rel_types: Optional[str] = Query(
        "IS_MEMBER_OF,EXECUTED,INVOLVES,OF_DERIVATIVE,UNDERLYING_ASSET,ISSUED_BY",
        description="Comma-separated relationship types to expand",
    ),
):
    """
    Expand a selected Member into a GraphDTO of connected nodes/edges
    (committees, transactions, assets, derivatives, issuers).
    Frontend can merge this into the existing graph on persona click.
    """
    if not node_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_id is required")

    graph_base = _neo4j_service(
        session,
        label="",
        repo_type="base",
    )
    graph_service = GraphService(graph_base)

    parsed_rel_types = [
        part.strip()
        for part in (rel_types or "").split(",")
        if part.strip()
    ] or None

    neighborhood = await graph_service.get_node_neighborhood(
        node_id=node_id,
        depth=depth,
        rel_types=parsed_rel_types,
    )
    if neighborhood is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return neighborhood





# ── Collect both routers ──────────────────────────────────────────────────────

router.include_router(doc_router)
router.include_router(neo4j_router)
