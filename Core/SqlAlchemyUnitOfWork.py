
from Repository.documents_repository import PostgresRepository, StockRepository, CommitteeRepository
from Core.unit_of_work import AbstractUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session: AsyncSession):
        self._session = session
        self.documents = None # Placeholder

    async def __aenter__(self):
        # The UoW knows WHICH concrete repository to use
        self.documents = PostgresRepository(self._session)
        self.documents.schema_name = "oden"
        self.documents.table_name = "documents"
        self.documents.pk_name = "doc_id"

        # Configuration for Stocks
        self.stocks = StockRepository(self._session)
        self.stocks.schema_name = "oden"
        self.stocks.table_name = "stock_gains"
        self.stocks.pk_name = "id"

        # Configuration for Stocks
        self.queries = PostgresRepository(self._session)
        self.queries.schema_name = "oden"
        self.queries.table_name = "natural_language_queries"
        self.queries.pk_name = "id"


        # Configuration for Stocks
        self.committee = PostgresRepository(self._session)
        self.committee.schema_name = "oden"
        self.committee.table_name = "committee"
        self.committee.pk_name = "id"

        self.legislator = PostgresRepository(self._session)
        self.legislator.schema_name = "oden"
        self.legislator.table_name = "legislator"
        self.legislator.pk_name = "bioguide_id"

        self.committee_membership = CommitteeRepository(self._session)
        self.committee_membership.schema_name = "oden"
        self.committee_membership.table_name = "committee_membership"
        self.committee_membership.pk_name = "id"

        return self

    async def commit(self):
        await self._session.commit()

    async def rollback(self):
        await self._session.rollback()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        # For workers, we close; for FastAPI, this is usually 
        # handled by the session generator cleanup.
        await self._session.close()