import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar, Dict, List, Optional
import uuid
import re
from neo4j import AsyncSession as Neo4jSession
from datetime import datetime
from Schema.graph_schema import NodeDTO, GraphDTO, EdgeDTO, neo4j_to_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

    async def get_example_orm(self)->GraphDTO:
        member = MemberNode(full_name="Thomas H. Kean, Jr.")
        print(f"member: {member}")
        nodes = [self.to_dto(member, member.id)]
        print(f"nodes: {nodes}")
        return GraphDTO(
            nodes=nodes,
            edges=[],
        )

    async def search(self, filters: dict) -> GraphDTO:
        conditions = []
        params = {}

        for key, value in filters.items():
            if isinstance(value, float):
                conditions.append(
                    f"n.{key} >= ${key}"
                )
            elif isinstance(datetime.strptime(value, "%Y-%m-%d"), datetime):
                if key == "date_from":
                    conditions.append(
                        f"n.created_at >= datetime(${key})"
                    )
                elif key == "date_to":
                    conditions.append(
                        f"n.created_at <= datetime(${key})"
                    )
                else:
                    raise ValueError(f"Invalid date format: {value}")
            else:
                conditions.append(
                    f"toLower(n.{key}) CONTAINS toLower(${key})"
                )
            params[key] = value.lower() if isinstance(value, str) else value

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        cypher = f"""
            MATCH (n:{self.label})
            {where_clause}
            RETURN n AS node, elementId(n) as id
        """
        result = await self._session.run(cypher, **params)
        records = await result.data()
        print(f"records: {records}")
        return records

    async def get_committee(self, committee: Optional[str] = None) -> GraphDTO | None:
        conditions = []
        params = {}

        if committee:
            conditions.append("toLower(c.chamber) CONTAINS toLower($committee)")
            params["committee"] = committee

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        cypher = f"""
            MATCH (c:Committee)
            OPTIONAL MATCH (c)<-[r:IS_MEMBER_OF]-(m:Member)
            {where_clause}
            RETURN 
                c as committee_node,
                elementId(c) as committee_id,
                COLLECT(DISTINCT {{
                    member_node: m,
                    member_id: coalesce(m.bioguide_id, elementId(m)),
                    relationship: r,
                    relationship_id: elementId(r)
                }}) as members
        """

        result = await self._session.run(cypher, **params)
        records = await result.data()
        
        nodes = []
        edges = []
        node_ids = set()
        
        for record in records:
            committee_node = record["committee_node"]
            committee_id = record["committee_id"]
            
            # Add committee node (once)
            if committee_id not in node_ids:
                committee_data = neo4j_to_dict(committee_node)
                
                nodes.append(NodeDTO(
                    id=committee_id,
                    type="Committee",
                    data=committee_data
                ))
                node_ids.add(committee_id)
            
            # Process members
            for member_info in record["members"]:
                member_node = member_info["member_node"]
                
                # Skip if no member
                if not member_node:
                    continue
                    
                member_id = member_info["member_id"]
                relationship = member_info["relationship"]
                relationship_id = member_info["relationship_id"] or str(uuid.uuid4())
                
                # Add member node (once)
                if member_id not in node_ids:
                    member_data = neo4j_to_dict(member_node)
                    
                    nodes.append(NodeDTO(
                        id=member_id,
                        type="Member",
                        data=member_data
                    ))
                    node_ids.add(member_id)
                
                # Add edge
                relationship_data = neo4j_to_dict(relationship)
                
                edges.append(EdgeDTO(
                    id=str(uuid.uuid4()) if not relationship_id else relationship_id,
                    source=member_id,
                    target=committee_id,
                    type="IS_MEMBER_OF",
                    data=relationship_data
                ))
        
        return GraphDTO(nodes=nodes, edges=edges)
        

    async def get_assets(self)->List[Dict[str, Any]]:
        cypher = """
            MATCH(a:Asset)
            OPTIONAL MATCH (a)-[:ISSUED_BY]->(i:Issuer)
            RETURN 
                a.ticker    AS ticker,
                a.type      AS asset_type,
                i.name      AS issuer_name
            ORDER BY a.ticker ASC
        """
        result = await self._session.run(cypher)
        records = await result.data()
        return [
        {
            "ticker":      record["ticker"],
            "asset_type":  record["asset_type"],
            "issuer_name": record["issuer_name"],
        }
            for record in records
        ]
    
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

    async def get_by_id(self, record_id: str) -> NodeDTO | None:
        cypher = """
        MATCH (n)
        WHERE elementId(n) = $id
        RETURN elementId(n) AS id, n
        """

        result = await self._session.run(cypher, id=record_id)
        record = await result.single()

        if not record:
            return None

        node = record["n"]
        element_id = record["id"]

        return self.to_dto(node, element_id)


    async def get_by_bioguide_id(self, bioguide_id: str) -> NodeDTO | None:
        cypher = """
        MATCH (n)
        WHERE n.bioguide_id = $bioguide_id
        RETURN elementId(n) AS id, n
        """
        result = await self._session.run(cypher, bioguide_id=bioguide_id)
        record = await result.single()

        if not record:
            return None

        node = record["n"]
        element_id = record["id"]

        return self.to_dto(node, element_id)

    async def get_node_neighborhood(
        self,
        node_id: str,
        depth: int = 2,
        rel_types: Optional[List[str]] = None,
    ) -> GraphDTO | None:
        """
        Expand a Member into a GraphDTO: committees, transactions,
        assets, derivatives, and issuers based on requested relationship types.

        depth=1: Member -> Committee + Transaction
        depth=2: also Asset / Derivative / Issuer hops from those transactions
        """
        allowed = rel_types or [
            "IS_MEMBER_OF",
            "EXECUTED",
            "INVOLVES",
            "OF_DERIVATIVE",
            "UNDERLYING_ASSET",
            "ISSUED_BY",
        ]
        include_member_of = "IS_MEMBER_OF" in allowed
        include_executed = "EXECUTED" in allowed
        include_involves = "INVOLVES" in allowed and depth >= 2
        include_derivative = "OF_DERIVATIVE" in allowed and depth >= 2
        include_underlying = "UNDERLYING_ASSET" in allowed and depth >= 2
        include_issued_by = "ISSUED_BY" in allowed and depth >= 2

        cypher = """
            MATCH (m:Member)
            WHERE elementId(m) = $id OR m.bioguide_id = $id OR m.id = $id

            OPTIONAL MATCH (m)-[r_mem:IS_MEMBER_OF]->(c:Committee)
            WHERE $include_member_of

            OPTIONAL MATCH (m)-[r_exec:EXECUTED]->(t:Transaction)
            WHERE $include_executed

            OPTIONAL MATCH (t)-[r_inv:INVOLVES]->(a:Asset)
            WHERE $include_involves AND t IS NOT NULL

            OPTIONAL MATCH (t)-[r_der:OF_DERIVATIVE]->(d:Derivative)
            WHERE $include_derivative AND t IS NOT NULL

            OPTIONAL MATCH (d)-[r_und:UNDERLYING_ASSET]->(a2:Asset)
            WHERE $include_underlying AND d IS NOT NULL

            OPTIONAL MATCH (a)-[r_iss:ISSUED_BY]->(i:Issuer)
            WHERE $include_issued_by AND a IS NOT NULL

            OPTIONAL MATCH (a2)-[r_iss2:ISSUED_BY]->(i2:Issuer)
            WHERE $include_issued_by AND a2 IS NOT NULL

            RETURN
                m AS member_node,
                coalesce(m.bioguide_id, elementId(m)) AS member_id,
                elementId(m) AS member_element_id,
                collect(DISTINCT {
                    node: c,
                    node_id: elementId(c),
                    relationship: r_mem,
                    relationship_id: elementId(r_mem)
                }) AS committees,
                collect(DISTINCT {
                    node: t,
                    node_id: coalesce(t.id, elementId(t)),
                    relationship: r_exec,
                    relationship_id: elementId(r_exec)
                }) AS transactions,
                collect(DISTINCT {
                    node: a,
                    node_id: coalesce(a.ticker, elementId(a)),
                    relationship: r_inv,
                    relationship_id: elementId(r_inv),
                    source_id: coalesce(t.id, elementId(t))
                }) AS assets,
                collect(DISTINCT {
                    node: d,
                    node_id: coalesce(d.contract_id, elementId(d)),
                    relationship: r_der,
                    relationship_id: elementId(r_der),
                    source_id: coalesce(t.id, elementId(t))
                }) AS derivatives,
                collect(DISTINCT {
                    node: a2,
                    node_id: coalesce(a2.ticker, elementId(a2)),
                    relationship: r_und,
                    relationship_id: elementId(r_und),
                    source_id: coalesce(d.contract_id, elementId(d))
                }) AS underlying_assets,
                collect(DISTINCT {
                    node: i,
                    node_id: coalesce(i.name, elementId(i)),
                    relationship: r_iss,
                    relationship_id: elementId(r_iss),
                    source_id: coalesce(a.ticker, elementId(a))
                }) AS issuers,
                collect(DISTINCT {
                    node: i2,
                    node_id: coalesce(i2.name, elementId(i2)),
                    relationship: r_iss2,
                    relationship_id: elementId(r_iss2),
                    source_id: coalesce(a2.ticker, elementId(a2))
                }) AS underlying_issuers
        """
        result = await self._session.run(
            cypher,
            id=node_id,
            include_member_of=include_member_of,
            include_executed=include_executed,
            include_involves=include_involves,
            include_derivative=include_derivative,
            include_underlying=include_underlying,
            include_issued_by=include_issued_by,
        )
        record = await result.single()
        if not record or not record["member_node"]:
            return None

        nodes: List[NodeDTO] = []
        edges: List[EdgeDTO] = []
        node_ids: set = set()
        edge_ids: set = set()

        def add_node(node_id_value: str, node_type: str, node_obj) -> None:
            if not node_obj or not node_id_value or node_id_value in node_ids:
                return
            nodes.append(NodeDTO(
                id=str(node_id_value),
                type=node_type,
                data=neo4j_to_dict(node_obj),
            ))
            node_ids.add(str(node_id_value))

        def add_edge(
            edge_id: Optional[str],
            source: str,
            target: str,
            edge_type: str,
            rel_obj,
        ) -> None:
            if not source or not target:
                return
            eid = str(edge_id) if edge_id else str(uuid.uuid4())
            if eid in edge_ids:
                return
            edge_ids.add(eid)
            edges.append(EdgeDTO(
                id=eid,
                source=str(source),
                target=str(target),
                type=edge_type,
                data=neo4j_to_dict(rel_obj) if rel_obj else None,
            ))

        member_id = record["member_id"] or record["member_element_id"]
        add_node(member_id, "Member", record["member_node"])

        for item in record["committees"] or []:
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Committee", item["node"])
            add_edge(
                item.get("relationship_id"),
                member_id,
                item["node_id"],
                "IS_MEMBER_OF",
                item.get("relationship"),
            )

        for item in record["transactions"] or []:
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Transaction", item["node"])
            add_edge(
                item.get("relationship_id"),
                member_id,
                item["node_id"],
                "EXECUTED",
                item.get("relationship"),
            )

        for item in record["assets"] or []:
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Asset", item["node"])
            add_edge(
                item.get("relationship_id"),
                item.get("source_id"),
                item["node_id"],
                "INVOLVES",
                item.get("relationship"),
            )

        for item in record["derivatives"] or []:
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Derivative", item["node"])
            add_edge(
                item.get("relationship_id"),
                item.get("source_id"),
                item["node_id"],
                "OF_DERIVATIVE",
                item.get("relationship"),
            )

        for item in record["underlying_assets"] or []:
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Asset", item["node"])
            add_edge(
                item.get("relationship_id"),
                item.get("source_id"),
                item["node_id"],
                "UNDERLYING_ASSET",
                item.get("relationship"),
            )

        for item in (record["issuers"] or []) + (record["underlying_issuers"] or []):
            if not item or not item.get("node"):
                continue
            add_node(item["node_id"], "Issuer", item["node"])
            add_edge(
                item.get("relationship_id"),
                item.get("source_id"),
                item["node_id"],
                "ISSUED_BY",
                item.get("relationship"),
            )

        return GraphDTO(nodes=nodes, edges=edges)

    def _stable_graph_node_id(self, node) -> str:
        props = neo4j_to_dict(node)
        for key in ("bioguide_id", "ticker", "contract_id", "id", "name", "committee_id"):
            value = props.get(key)
            if value is not None and str(value).strip() != "":
                return str(value)
        return str(getattr(node, "element_id", None) or id(node))

    def _graph_node_type(self, node) -> str:
        labels = list(getattr(node, "labels", []) or [])
        for preferred in (
            "Member",
            "Committee",
            "Transaction",
            "Asset",
            "Issuer",
            "Derivative",
            "CallOption",
        ):
            if preferred in labels:
                return preferred
        return labels[0] if labels else "Node"

    def _is_neo4j_node(self, value: Any) -> bool:
        return hasattr(value, "labels") and hasattr(value, "element_id")

    def _is_neo4j_relationship(self, value: Any) -> bool:
        return (
            hasattr(value, "type")
            and hasattr(value, "start_node")
            and hasattr(value, "end_node")
            and hasattr(value, "element_id")
        )

    def _is_neo4j_path(self, value: Any) -> bool:
        return hasattr(value, "nodes") and hasattr(value, "relationships")

    def _records_to_graph_dto(self, records: List[Any]) -> GraphDTO:
        """Convert Neo4j query records containing nodes/rels/paths into GraphDTO."""
        nodes: List[NodeDTO] = []
        edges: List[EdgeDTO] = []
        node_ids: set = set()
        edge_ids: set = set()

        def add_node(node) -> Optional[str]:
            if not self._is_neo4j_node(node):
                return None
            node_id = self._stable_graph_node_id(node)
            if node_id not in node_ids:
                nodes.append(NodeDTO(
                    id=node_id,
                    type=self._graph_node_type(node),
                    data=neo4j_to_dict(node),
                ))
                node_ids.add(node_id)
            return node_id

        def add_relationship(rel) -> None:
            if not self._is_neo4j_relationship(rel):
                return
            source = add_node(rel.start_node)
            target = add_node(rel.end_node)
            if not source or not target:
                return
            edge_id = str(getattr(rel, "element_id", None) or uuid.uuid4())
            if edge_id in edge_ids:
                return
            edge_ids.add(edge_id)
            edges.append(EdgeDTO(
                id=edge_id,
                source=source,
                target=target,
                type=str(rel.type),
                data=neo4j_to_dict(rel),
            ))

        def walk(value: Any) -> None:
            if value is None:
                return
            if self._is_neo4j_node(value):
                add_node(value)
                return
            if self._is_neo4j_relationship(value):
                add_relationship(value)
                return
            if self._is_neo4j_path(value):
                for n in value.nodes:
                    add_node(n)
                for r in value.relationships:
                    add_relationship(r)
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    walk(item)
                return
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)

        for record in records:
            # neo4j.Record supports .values() / iteration
            try:
                values = record.values()
            except Exception:
                values = list(record) if record is not None else []
            for value in values:
                walk(value)

        return GraphDTO(nodes=nodes, edges=edges)

    async def run_cypher_to_graph(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> GraphDTO:
        """
        Execute a read-only Cypher query and map node/relationship/path
        results into a GraphDTO for the frontend.
        """
        forbidden = ["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "CALL"]
        for kw in forbidden:
            if re.search(rf"\b{kw}\b", cypher or "", re.IGNORECASE):
                raise ValueError(f"Write/procedure operation '{kw}' is not permitted.")

        result = await self._session.run(cypher, **(params or {}))
        raw_records = [record async for record in result]
        return self._records_to_graph_dto(raw_records)

    async def create(self, data: dict[str, Any]) -> T:
        """Create a new node."""
        # Remove id if present (let Neo4j generate)
        logger.info(f"Data being sent to Neo4j: {data}")
        props = ", ".join([f"n.{k} = ${k}" for k in data.keys()])
        cypher = f"""
            CREATE (n:{self.label})
                SET {props}
            RETURN n
        """
        logging.info(cypher)
        result = await self._session.run(cypher, **data)
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

    def to_dto(self, node, element_id: str):
        return NodeDTO(
            id=element_id,
            type=list(node.labels)[0],
            data=dict(node)
        )

class TransactionRepository(Neo4jRepository):
    """ Repository for Transaction data"""

    # ── Filer (Person) ────────────────────────────────────────────────────────
    async def merge_filer(self, data: Dict[str, Any]) -> str:
        """Merge the Person/Filer and their District."""
        try:
            state_district = data.get("state_district") or ""
            cypher = """
            MERGE (p:Member {bioguide_id: $bioguide_id})
            ON CREATE SET
                p.id = randomUUID(),
                p.first_name = $first_name,
                p.last_name = $last_name,
                p.full_name = $full_name,
                p.state_district = $state_district,
                p.state = $state,
                p.created_at = datetime()
            SET
                p.first_name = coalesce($first_name, p.first_name),
                p.last_name = coalesce($last_name, p.last_name),
                p.full_name = coalesce($full_name, p.full_name),
                p.state_district = coalesce($state_district, p.state_district),
                p.state = coalesce($state, p.state),
                p.status = coalesce($status, p.status),
                p.last_updated = datetime()
            RETURN p.bioguide_id as bioguide_id
            """
            params = {
                "bioguide_id": data["bioguide_id"],
                "first_name": data.get("first_name"),
                "last_name": data.get("last_name"),
                "full_name": data.get("full_name"),
                "status": data.get("status"),
                "state_district": state_district or None,
                "state": state_district[:2] if state_district else data.get("state"),
            }
            result = await self._session.run(
                cypher,
                **params
            )
            record = await result.single()
            return record["bioguide_id"]
        except Exception as e:
                logger.info(f"[GRAPH_REPO] Error merge_filer: {e}")
                raise e

    async def merge_asset(self, tx: Dict[str, Any]) -> str:
        """Merge Issuer and Asset, then link them."""
        if tx.get("ticker") is None:
            return
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

        if metadata and metadata.get("strike_price") is None:
            return

        if metadata and metadata.get("ticker") is None:
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
            expiry=tx["transaction_date"]
        )

    def parse_date(self, date_str):
        for fmt in ["%m-%d-%Y", "%m/%d/%Y"]:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    # ── Transaction (The Event) ──────────────────────────────────────────────
    async def create_transaction(self, tx: Dict[str, Any], bioguide_id: str, filing_id: str) -> str:
        try:
            """Create the central Transaction node and connect to Filer and Asset."""
            if tx and tx.get("ticker") is None:
                return
            tx_id = str(uuid.uuid4())
            date_obj = self.parse_date(tx["transaction_date"])
            if date_obj is None:
                return 
            formatted_date = date_obj.strftime("%Y-%m-%d")
            ## Note: Transaction is not idempodent, it will create a new transaction if it doesn't exist.
            cypher = """
                MERGE (p:Member {bioguide_id: $bioguide_id})
                MERGE (a:Asset {ticker: $ticker})
                CREATE (t:Transaction {
                    id: $tx_id,
                    doc_id: $filing_id,
                    type: $type,
                    trade_date: date($date),
                    amount_range: $amount,
                    description: $desc,
                    committee_relevance_score: $score,
                    matched_committee_id: $committee_id,
                    matched_committee_name: $committee_name,
                    relevance_method: $method,
                    created_at: datetime()
                })
                CREATE (p)-[:EXECUTED]->(t)
                CREATE (t)-[:INVOLVES]->(a)
                RETURN t.id as transaction_id
            """
            
            result = await self._session.run(
                query=cypher,
                bioguide_id=bioguide_id,
                ticker=tx["ticker"],
                tx_id=tx_id,
                filing_id=filing_id,
                type=tx["transaction_type"],
                date=formatted_date,
                amount=tx["amount_range"],
                desc=tx.get("description"),
                score=tx.get("committee_relevance_score"),
                committee_id=tx.get("matched_committee_id"),
                committee_name=tx.get("matched_committee_name"),
                method=tx.get("relevance_method"),
            )
            record = await result.single()
            return record["transaction_id"] if record else None
        except Exception as e:
            logger.info(f"[GRAPH_REPO] Error create_transaction: {e}")
            raise e

    # ── Orchestrator ──────────────────────────────────────────────────────────


class CommitteeRepository(Neo4jRepository):
    """ Repository for committee data"""
    """ 
        This constrain is required, race condition can cause await to handle another request, creating duplicates. (Concurency)
        CREATE CONSTRAINT committee_id_unique IF NOT EXISTS
        FOR (c:Committee) REQUIRE c.id IS UNIQUE;
    """


    async def merge_committee_member(self, data: Dict[str, Any]) -> str:
        cypher = """
            MATCH (c:Committee {id: $committee_id})
            MERGE (m:Member {bioguide_id: $bioguide_id})
            ON CREATE SET
                m.id         = $member_id,
                m.first_name = $first_name,
                m.last_name  = $last_name,
                m.chamber    = $chamber,
                m.party      = $party,
                m.state      = $state,
                m.created_at = datetime()
            ON MATCH SET
                m.leadership_role = $leadership_role,
                m.chamber         = $chamber,
                m.party           = $party,
                m.updated_at      = datetime()
            MERGE (m)-[r:IS_MEMBER_OF]->(c)
            ON CREATE SET r.role       = $role,
                        r.created_at = datetime()
            RETURN c.committee_id AS committee_id, m.bioguide_id AS member_id
        """
        result = await self._session.run(
            cypher,
            committee_id=data['id'],
            member_id=str(data.get('member_id', '')),
            bioguide_id=data['bioguide_id'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            chamber=data['chamber'],
            leadership_role=data.get('leadership_role'),
            party=data['party'],
            state=data['state'],
            role=data.get('role', 'Member'),
        )
        record = await result.single()
        return record