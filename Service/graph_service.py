import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Repository.graph_repository import AbstractRepository
from typing import Any, Generic, Sequence, TypeVar, Dict, List
from MessageBroker.rabbitmq_client import rabbitmq_client

T = TypeVar("T")


class BaseService(Generic[T]):
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, repository: AbstractRepository[T]):
        self._repo = repository

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_assets(self)->List[Dict[str, Any]] | None:
        """ Retrive all assets withg their linked"""
        result = await self._repo.get_assets(cypher)
        return resul

    # ── Write ─────────────────────────────────────────────────────────────────

    async def ingest_filing(self, result: Dict[str, Any]) -> str:
        """
        Orchestrates the ingestion of a full filing result.
        """
        # 1. Handle the Person
        filer_id = await self._repo.merge_filer(result)

        # 2. Iterate through Transactions
        for tx_data in result.get("transactions", []):
            # Create the Asset/Issuer backbone
            await self._repo.merge_asset(tx_data)
            
            # Create the Transaction event
            tx_id = await self._repo.create_transaction(
                tx_data, 
                filer_id, 
                result["filing_id"]
            )
            if tx_id:
                # Handle complexity if it exists
                await self._repo.merge_derivative(tx_data, tx_id)

        return result["filing_id"]

    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        return await self._repo.update(record_id, data)

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self._repo.delete(record_id)
