from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from Repository.documents_repository import AbstractRepository, CommitteeRepository


# Assuming T is your Document model type
T = TypeVar("T")

class AbstractUnitOfWork(ABC):
    # This acts as a contract. Every UoW must have this.
    documents: AbstractRepository
    stocks: AbstractRepository
    queries: AbstractRepository
    committee: AbstractRepository
    legislator: AbstractRepository
    committee_membership: CommitteeRepository

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # If an exception occurred inside the 'async with' block, roll back automatically.
        if exc_type is not None:
            await self.rollback()
        # Note: We do NOT commit here. The Service must call commit() explicitly.

    @abstractmethod
    async def commit(self):
        """Implement database-specific commit logic."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self):
        """Implement database-specific rollback logic."""
        raise NotImplementedError