import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
import logging
import zipfile
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")


class TransactionsExtractionService:
    """
    Transactions Extraction Service
    """
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────

    async def create_transactions_extraction(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a transactions extraction record.
        """
        try:
            async with self.uow:
                transactions_extraction = await self.uow.transactions_extraction.create(data)
                await self.uow.commit()
                return transactions_extraction
        except Exception as e:
            logger.error(f"[Transactions Extraction Service] Failed to create transactions extraction: {e}")
            return None


    # ── Write ─────────────────────────────────────────────────────────────────
