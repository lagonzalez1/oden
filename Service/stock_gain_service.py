import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Repository.documents_repository import AbstractRepository
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, Generic, Sequence, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
from Schema.base_schema import GetAssociatedTransactions, GetPerformanceRequest
import logging
import zipfile
import requests
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")


class StockGainsService:
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────


    # ── Write ─────────────────────────────────────────────────────────────────


    async def get_associated_transactions(self, request: Optional[GetAssociatedTransactions]):
        try:
            update_count = 0
            async with self.uow:
                results = await self.uow.stocks.get_by_ids(request.doc_ids)
            return results if results else None
        except Exception as e:
            logger.error(f"[Document Service] create_transaction_gains: {e}")
            raise

    async def get_clients(self)->Optional[List[Any]]:
        try:
            async with self.uow:
                results = await self.uow.stocks.get_distinct_clients()
                return results if results else None
        except Exception as e:
            logger.error(f"[Document Service] create_transaction_gains: {e}")
            raise

    async def get_client_performance(self, filer_name: str)->Optional[List[Any]]:
        try:
            async with self.uow:
                results = await self.uow.stocks.get_by_name(filer_name=filer_name)
                return results if results else None
        except Exception as e:
            logger.error(f"[Document Service] create_transaction_gains: {e}")
            raise


    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self.self.uow.documents.delete(record_id)
