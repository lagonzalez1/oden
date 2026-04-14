from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar, Dict
import uuid
from neo4j import AsyncSession as Neo4jSession

T = TypeVar("T")


# ── Shared contract ────────────────────────────────────────────────────────────

class AbstractRepository(ABC, Generic[T]):
    """Minimal interface every repository must satisfy."""

    @abstractmethod
    async def get_table(self, **filters) -> Sequence[T]:
        """Return rows / nodes from the underlying store."""
        ...

    @abstractmethod
    async def get_by_id(self, record_id: Any) -> T | None:
        ...

    @abstractmethod
    async def create(self, data: dict[str, Any]) -> T:
        ...

    @abstractmethod
    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def delete(self, record_id: Any) -> bool:
        ...
# ── Neo4j base repo ────────────────────────────────────────────────────────────

class Neo4jRepository(AbstractRepository[T]):
    """
    Concrete base for Neo4j repositories.

    Subclass and set `label` to the node label you are working with.
    """

    label: str = ""  # override in subclass e.g. "User"


    def __init__(self, session: Neo4jSession):
        self._session = session
    
        # ── Implement required abstract methods ──────────────────────────────────
    
    async def get_table(self, **filters) -> Sequence[T]:
        """Return nodes from Neo4j."""
        cypher = f"MATCH (n:{self.label}) RETURN n"
        # Add filters if provided
        if filters:
            conditions = [f"n.{k} = ${k}" for k in filters.keys()]
            cypher += " WHERE " + " AND ".join(conditions)
        
        result = await self._session.run(cypher, **filters)
        records = await result.values()
        # Transform Neo4j records to your T type as needed
        return [record[0] for record in records] if records else []

    async def get_by_id(self, record_id: Any) -> T | None:
        """Get node by ID."""
        cypher = f"MATCH (n:{self.label} {{id: $id}}) RETURN n"
        result = await self._session.run(cypher, id=record_id)
        record = await result.single()
        return record[0] if record else None

    async def create(self, data: dict[str, Any]) -> T:
        """Create a new node."""
        # Remove id if present (let Neo4j generate)
        data_copy = {k: v for k, v in data.items() if k != 'id'}
        props = ", ".join([f"n.{k} = ${k}" for k in data_copy.keys()])
        cypher = f"""
        CREATE (n:{self.label})
        SET {props}
        RETURN n
        """
        result = await self._session.run(cypher, **data_copy)
        record = await result.single()
        return record[0]

    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update an existing node."""
        sets = ", ".join([f"n.{k} = ${k}" for k in data.keys()])
        cypher = f"""
        MATCH (n:{self.label} {{id: $id}})
        SET {sets}, n.last_updated = datetime()
        RETURN n
        """
        result = await self._session.run(cypher, id=record_id, **data)
        record = await result.single()
        return record[0] if record else None

    async def delete(self, record_id: Any) -> bool:
        """Delete a node."""
        cypher = f"""
        MATCH (n:{self.label} {{id: $id}})
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        result = await self._session.run(cypher, id=record_id)
        record = await result.single()
        return record["deleted"] > 0 if record else False


class TransactionRepository(Neo4jRepository):
    """ Repository for Transaction data"""

    # ── Filer (Person) ────────────────────────────────────────────────────────
    async def merge_filer(self, data: Dict[str, Any]) -> str:
        """Merge the Person/Filer and their District."""
        cypher = """
        MERGE (p:Person {name: $name})
        SET p.status = $status,
            p.state_district = $state_district,
            p.last_updated = datetime()
        RETURN p.name as filer_id
        """
        params = {
        "name": data["name"],
        "status": data["status"],
        "state_district": data["state_district"]
        }
        result = await self._session.run(
            cypher,
            **params
        )
        record = await result.single()
        return record["filer_id"]

    async def merge_asset(self, tx: Dict[str, Any]) -> str:
        """Merge Issuer and Asset, then link them."""
        cypher = """
        MERGE (i:Issuer {name: $issuer_name})
        MERGE (a:Asset {ticker: $ticker})
        ON CREATE SET a.type = $asset_type
        MERGE (a)-[:ISSUED_BY]->(i)
        RETURN a.ticker as asset_id
        """
        result = await self._session.run(
            cypher,
            issuer_name=tx["asset_name"],
            ticker=tx["ticker"],
            asset_type=tx["asset_type"]
        )
        record = await result.single()
        return record["asset_id"]

    # ── Derivatives ───────────────────────────────────────────────────────────
    async def merge_derivative(self, tx: Dict[str, Any], transaction_id: str):
        """Handle complex instruments like Call Options."""
        metadata = tx.get("metadata")
        if not metadata or not metadata.get("instrument"):
            return

        cypher = """
        MATCH (t:Transaction {id: $tx_id})
        MATCH (a:Asset {ticker: $ticker})
        MERGE (d:Derivative:CallOption {
            contract_id: $ticker + "-" + $strike + "-" + $expiry
        })
        SET d.strike_price = $strike,
            d.expiration_date = date($expiry)
        MERGE (d)-[:UNDERLYING_ASSET]->(a)
        MERGE (t)-[:OF_DERIVATIVE]->(d)
        """
        await self._session.run(
            cypher,
            tx_id=transaction_id,
            ticker=tx["ticker"],
            strike=metadata.get("strike_price"),
            expiry=tx["transaction_date"] # Using trade date as proxy if expiry not explicit
        )
    
    # ── Transaction (The Event) ──────────────────────────────────────────────
    async def create_transaction(self, tx: Dict[str, Any], filer_name: str, filing_id: str) -> str:
        """Create the central Transaction node and connect to Filer and Asset."""
        tx_id = str(uuid.uuid4())
        cypher = """
        MATCH (p:Person {name: $filer_name})
        MATCH (a:Asset {ticker: $ticker})
        CREATE (t:Transaction {
            id: $tx_id,
            doc_id: $filing_id,
            type: $type,
            trade_date: date($date),
            amount_range: $amount,
            description: $desc,
            created_at: datetime()
        })
        CREATE (p)-[:EXECUTED]->(t)
        CREATE (t)-[:INVOLVES]->(a)
        RETURN t.id as transaction_id
        """
        result = await self._session.run(
            query=cypher,
            filer_name=filer_name,
            ticker=tx["ticker"],
            tx_id=tx_id,
            filing_id=filing_id,
            type=tx["transaction_type"],
            date=tx["transaction_date"],
            amount=tx["amount_range"],
            desc=tx.get("description")
        )
        record = await result.single()
        return record["transaction_id"]

    # ── Orchestrator ──────────────────────────────────────────────────────────

    async def ingest_filing(self, result: Dict[str, Any]) -> str:
        """
        Orchestrates the ingestion of a full filing result.
        """
        # 1. Handle the Person
        filer_id = await self.merge_filer(result)

        # 2. Iterate through Transactions
        for tx_data in result.get("transactions", []):
            # Create the Asset/Issuer backbone
            await self.merge_asset(tx_data)
            
            # Create the Transaction event
            tx_id = await self.create_transaction(
                tx_data, 
                filer_id, 
                result["filing_id"]
            )
            
            # Handle complexity if it exists
            await self.merge_derivative(tx_data, tx_id)

        return result["filing_id"]