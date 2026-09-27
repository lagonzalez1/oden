from sqlalchemy import text
from Repository.base_repository import PostgresRepository
from typing import Any

class LegislatorRepository(PostgresRepository):
    table_name = "legislator"
    schema_name = "oden"
    pk_name = "id"

    @property
    def full_table_name(self) -> str:
        """Returns the escaped full path: "schema"."table" """
        return f'{self.schema_name}.{self.table_name}'

    async def get_by_col(self, col: str, col_val: str) ->Any | None:
        query = text(f"SELECT * FROM {self.full_table_name} WHERE {col} = :id")
        result = await self._session.execute(query, {"id": col_val})
        return result.mappings().first()

    ## Get legislator by name and or state_district
    async def get_legislator_by_name(self, first_name: str, last_name: str):
        params = {
            "first_name": f"%{first_name}%",
            "last_name": f"%{last_name}%",
            "official_full": f"%{first_name} {last_name}%",
        }

        query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE (first_name ILIKE :first_name
            AND last_name ILIKE :last_name) OR official_full ILIKE :official_full
        """)
        result = await self._session.execute(query, params)
        row = result.mappings().first()
        if row:
            return row

        # Fallback: match official_full against "first_name last_name"
        fallback_query = text(f"""
            SELECT * FROM {self.full_table_name}
            WHERE official_full ILIKE :official_full
        """)
        result = await self._session.execute(fallback_query, params["official_full"])
        return result.mappings().first()

    ## GEt legislator by bioguide_id
    async def get_legislator_by_bioguide_id(self, bioguide_id: str):
        query = text(f"SELECT * FROM {self.full_table_name} WHERE bioguide_id = :bioguide_id")
        result = await self._session.execute(query, {"bioguide_id": bioguide_id})
        return result.mappings().first()
    
    