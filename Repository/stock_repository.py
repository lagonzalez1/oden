from typing import List, Any
from sqlalchemy import text
from Repository.base_repository import PostgresRepository


class StockRepository(PostgresRepository):
    table_name = "stock_gains"
    schema_name = "oden"
    pk_name = "id"

    async def get_distinct_clients(self):
        query = text(f"SELECT DISTINCT filer_name FROM {self.full_table_name}")
        result = await self._session.execute(query)
        return result.mappings().all()

    async def get_by_doc_id(
        self,
        doc_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Any]:
        query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE doc_id = :doc_id
            ORDER BY trade_date DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self._session.execute(query, {
            "doc_id": doc_id,
            "limit":  limit,
            "offset": offset
        })
        return result.mappings().all()

    async def get_by_name(
        self,
        filer_name: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Any]:
        query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE filer_name ILIKE :filer_name
            ORDER BY trade_date DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self._session.execute(query, {
            "filer_name": f"%{filer_name}%",
            "limit":      limit,
            "offset":     offset
        })
        return result.mappings().all()
    
