import logging
from datetime import datetime
from Repository.graph_repository import AbstractRepository
from typing import Any, Generic, TypeVar, Dict, List, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
from Schema.graph_schema import NodeDTO, GraphDTO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


T = TypeVar("T")


class GraphService(Generic[T]):
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, repository: AbstractRepository[T]):
        self._repo = repository

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_committees(self, committee: Optional[str] = None)->GraphDTO | None:
        """ Retrive all assets withg their linked"""
        result = await self._repo.get_committee(committee=committee)
        return result


    async def search(self, filters: Optional[Dict[str, Any]] = None)->GraphDTO:
        """ Search the graph for nodes with the given label and filters. """
        return await self._repo.search(filters=filters or {})

    async def get_assets(self)->List[Dict[str, Any]] | None:
        """ Retrive all assets withg their linked"""
        result = await self._repo.get_assets()
        return result

    async def get_node_by_id(self, id):
        by_id_result = await self._repo.get_by_id(record_id=id)
        if by_id_result is not None:
            return by_id_result

        by_bioguide_id_result = await self._repo.get_by_bioguide_id(bioguide_id=id)
        return by_bioguide_id_result

    async def get_node_neighborhood(
        self,
        node_id: str,
        depth: int = 2,
        rel_types: Optional[List[str]] = None,
    ) -> GraphDTO | None:
        """
        Return a Member-centered subgraph (committees, transactions, assets).
        """
        return await self._repo.get_node_neighborhood(
            node_id=node_id,
            depth=depth,
            rel_types=rel_types,
        )

    async def run_cypher_to_graph(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> GraphDTO:
        """Execute a stored/generated Cypher query and return GraphDTO."""
        return await self._repo.run_cypher_to_graph(cypher=cypher, params=params)

    
    async def get_node_by_label(
        self,
        label: str,
        filters: Optional[Dict[str, Any]] = None,
    ):
        """
        Lookup nodes by label + frontend filter params.
        Repo implementation is responsible for Cypher; this layer only forwards.
        """

        return await self._repo.search(filters=filters or {})


    # ── Write ─────────────────────────────────────────────────────────────────

    async def ingest_filing(self, llm_content: Dict[str, Any]) -> str:
        """ Orchestrates the ingestion of a full filing result. """
        # 1. Handle the Person id
        bioguide_id = await self._repo.merge_filer(llm_content)

        # 2. Iterate through Transactions
        for tx_data in llm_content.get("transactions", []):
            # Create the Asset/Issuer backbone

            await self._repo.merge_asset(tx_data)
            
            # Create the Transaction event
            tx_id = await self._repo.create_transaction(
                tx_data, 
                bioguide_id, 
                llm_content["filing_id"]
            )
            if tx_id:
                # Handle complexity if it exists
                await self._repo.merge_derivative(tx_data, tx_id)

        return llm_content["filing_id"]
    
    # ── Committee functions ─────────────────────────────────────────────────────────────────

    async def create_committee(self, data: List[Dict[str, Any]])-> int:
        """ Create the committee with return its id*  """
        cnt = 0
        for i in range(0, len(data)):
            row = { "title": data[i].title, "id": str(data[i].id), "parent_committee_id": str(data[i].parent_committee_id), 
                   "committee_id": data[i].committee_id, "chamber": data[i].chamber, "office": data[i].office, "is_subcommittee": data[i].is_subcommittee}
            committee_node = await self._repo.create(row)
            if committee_node: cnt += 1
        return cnt

    async def merge_committee_member(self, data: Dict[str, Any]) ->None:
        """ Create the committee with return its id*  """
        cnt = 0
        for i in range(0, len(data)):
            legislator = { "first_name": data[i].first_name, "last_name": data[i].last_name, "bioguide_id": data[i].bioguide_id,
                          "committee_id": str(data[i].committee_id), "party": data[i].party, "leadership_role": data[i].leadership_role, 
                          "state": data[i].state, "chamber": data[i].chamber, "id": str(data[i].id) }
            legislator_node = await self._repo.merge_committee_member(dict(legislator))
            logger.info(legislator_node)
            if legislator_node: cnt += 1
            
        return cnt


    # ── Committee functions end ─────────────────────────────────────────────────────────────────
    
    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        return await self._repo.update(record_id, data)

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self._repo.delete(record_id)
    

    # ── Node transform ─────────────────────────────────────────────────────────────────
    async def to_dto(self, node: dict)->dict:
        return {
            "id": node.get("id"),
            "type": list(node.get("labels"))[0],
            "data": node
        }
