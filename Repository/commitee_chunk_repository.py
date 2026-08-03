from typing import List, Any, Optional
from sqlalchemy import text
from Repository.base_repository import PostgresRepository



class CommitteeChunkRepository(PostgresRepository):
    table_name = "committee_chunks"
    schema_name = "oden"
    pk_name = "id"

    async def get_chunks(self):
        pass

    async def search_similar(
        self,
        embedding: List[float],
        committee_ids: Optional[List[str]] = None,
        limit: int = 10,
        min_score: Optional[float] = None,
    ) -> List[Any]:
        """
        Cosine-similarity search of description embedding against committee_chunks.
        Optionally restrict to a set of committee UUIDs (e.g. a member's committees).
        """
        params: Dict[str, Any] = {
            "embedding": str(embedding),
            "limit": limit,
        }

        filters = ["cc.embedding IS NOT NULL"]
        if committee_ids:
            placeholders = ", ".join(f":cid_{i}" for i in range(len(committee_ids)))
            filters.append(f"cc.committee_id IN ({placeholders})")
            for i, cid in enumerate(committee_ids):
                params[f"cid_{i}"] = cid
        if min_score is not None:
            filters.append("(1 - (cc.embedding <=> CAST(:embedding AS vector))) >= :min_score")
            params["min_score"] = min_score

        where_clause = " AND ".join(filters)
        query = text(f"""
            SELECT
                cc.id AS chunk_id,
                cc.committee_id,
                cc.content_type,
                cc.chunk_index,
                cc.chunk_text,
                com.committee_id AS committee_code,
                com.title AS committee_title,
                com.chamber,
                com.is_subcommittee,
                1 - (cc.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM {self.full_table_name} cc
            JOIN oden.committee com ON com.id = cc.committee_id
            WHERE {where_clause}
            ORDER BY cc.embedding <=> CAST(:embedding AS vector) ASC
            LIMIT :limit
        """)
        result = await self._session.execute(query, params)
        return result.mappings().all()
