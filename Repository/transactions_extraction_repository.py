from sqlalchemy import text
from Repository.base_repository import PostgresRepository
from sqlalchemy.ext.asyncio import AsyncSession



class TransactionsExtractionRepository(PostgresRepository):
    schema_name = "oden"
    table_name = "transactions_extraction"
    pk_name = "id"
    

