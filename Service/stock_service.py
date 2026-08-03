import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
from Embeddings.main import EmbeddingService
import logging
import requests
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")


class StockService:
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_stock_by_ticker(self, ticker: str) -> Optional[Dict]:
        """Get stock information by ticker symbol."""
        try:
            async with self.uow:
                record = await self.uow.stock.get_by_col("ticker", ticker)
                await self.uow.commit()
                if record:                    
                    return record
                return None
        except Exception as e:
            logger.error(f"[Stock Service] Get stock by ticker failed for {ticker}: {e}")
            raise e

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create_stocks(self, stocks_data: List[Dict[str, Any]]) -> bool:
        """
        Insert multiple stocks into the database.
        
        Args:
            stocks_data: List of stock data dictionaries
            
        Returns:
            bool: True if successful
        """
        try:
            async with self.uow:
                for stock in stocks_data:
                    await self.uow.stock.create(stock)
                await self.uow.commit()
                logger.info(f"[Stock Service] Successfully inserted {len(stocks_data)} stocks")
                return True
        except Exception as e:
            logger.error(f"[Stock Service] Failed to insert stocks: {e}")
            raise e
    

    

