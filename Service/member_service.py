from datetime import datetime
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
from Embeddings.main import EmbeddingService
import logging
from Extract_external.main2 import HouseCommitteeParser
import xml.etree.ElementTree as ET
from Schema.base_schema import CommitteeEmbeddings
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")


class MemberService:
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────
    async def get_legislator_by_name(self, first_name: str, last_name: str, state_district: str)->List[Dict[str, any]]:
        try:
            async with self.uow:
                rows = await self.uow.legislator.get_legislator_by_name(first_name=first_name, last_name=last_name)
                self.uow.commit()
                return rows
        except Exception as e:
            logger.info(f"[Get committee error]: error: {e}")
            raise
    
    async def get_committees_relationships(self, chamber="Senate")->List[Dict[str, any]]:
        try:
            async with self.uow:
                rows = await self.uow.committee_membership.get_committee_membership(chamber=chamber)
                self.uow.commit()
                return rows
        except Exception as e:
            logger.info(f"[Get committee error]: error: {e}")
            raise

    # ── Write ────────────────────────────────────────────────────────────────
