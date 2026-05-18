from datetime import datetime
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
import logging
import xml.etree.ElementTree as ET
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")

""" Sentate xml files"""
committee_urls = [
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSAF.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSAP.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSAS.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSBK.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSCM.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSEG.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSEV.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSFI.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSFR.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSHR.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSGA.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SLIA.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSRA.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSSB.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSBU.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SSJU.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_JSTX.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SLIN.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_SCNC.xml",
    "https://www.senate.gov/general/committee_membership/committee_memberships_JCSE.xml"
]


class CommitteeService:
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_committees(self)->List[Dict[str, any]]:
        try:
            async with self.uow:
                rows = await self.uow.committee.get_table()
                self.uow.commit()
                return rows
        except Exception as e:
            logger.info(f"[Get committee error]: error: {e}")
            raise
    
    async def get_committees_relationships(self)->List[Dict[str, any]]:
        try:
            async with self.uow:
                rows = await self.uow.committee_membership.get_committee_membership()
                self.uow.commit()
                return rows
        except Exception as e:
            logger.info(f"[Get committee error]: error: {e}")
            raise


    # ── Write ────────────────────────────────────────────────────────────────

    async def download_and_parse_xml(self, url: Optional[str]):
        """Helper function to process xml files"""
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            xml_content = response.text
            root = ET.fromstring(xml_content)
            return root

    async def ingest_committee_data(self) ->None:
        """ Ingest all senate committees and its members. Writes to DB."""
        try:
            legislator_insert_cnt = 0
            committee_insert_cnt = 0
            sub_committee_insert_cnt = 0
            async with self.uow:
                for url in committee_urls:
                    root = await self.download_and_parse_xml(url)
                    for committee in root.findall("committees"):
                        majority_party, committee_name, committee_code = committee.findtext("majority_party"), committee.findtext("committee_name"), committee.findtext("committee_code")
                        committee_query = { "committee_id": committee_code, "parent_committee_id": None, "title": committee_name, "chamber": "Senate", "office": f"Majority-{majority_party}"}
                        committee_insert = await self.uow.committee.create(committee_query)
                        await self.uow.commit()
                        if committee_insert: committee_insert_cnt += 1
                    
                        members_node = committee.find("members")
                        if members_node is not None and committee_insert:
                            for member in members_node.findall("member"):
                                first_name, last_name = member.find("name/first").text, member.find("name/last").text
                                state, party = member.findtext("state"), member.findtext("party")
                                position = member.findtext("position")
                                legislator_query = { "bioguide_id": f"{state}:{party}:{first_name[0]}:{last_name[0]}", "first_name": first_name, 
                                                    "last_name": last_name, "party": party, "state": state, "chamber": "Senate", "leadership_role": position}
                                legislator_insert = await self.uow.legislator.upsert(
                                    data=legislator_query,
                                    conflict_column="bioguide_id"
                                )
                                await self.uow.commit()
                                if legislator_insert: legislator_insert_cnt += 1
                                membership_query = {"legislator_id": str(legislator_insert.id), "committee_id": str(committee_insert.id)}
                                await self.uow.committee_membership.create(membership_query)
                                await self.uow.commit()
                                    

                        for sub in committee.findall("subcommittee"):
                            subcommittee_name, subcommittee_code = sub.findtext("subcommittee_name"), sub.findtext("committee_code")
                            sub_committee_query = { "committee_id": subcommittee_code, "parent_committee_id": str(committee_insert.id), "title": subcommittee_name, 
                                                   "chamber": "Senate", "office": f"Majority-{majority_party}", "is_subcommittee": True }
                            sub_committee_insert = await self.uow.committee.create(sub_committee_query)
                            await self.uow.commit()
                            if sub_committee_insert: sub_committee_insert_cnt += 1
                            sub_members = sub.find("members")
                            if sub_members is not None:
                                for member in sub_members.findall("member"):
                                    first_name, last_name = member.find("name/first").text, member.find("name/last").text
                                    state, party = member.findtext("state"), member.findtext("party")
                                    position = member.findtext("position")
                                    sub_legislator_query = { "bioguide_id": f"{state}:{party}:{first_name[0]}:{last_name[0]}", "first_name": first_name, 
                                                            "last_name": last_name, "party": party, "state": state, "chamber": "Senate", "leadership_role": position}
                                    sub_legislator_insert = await self.uow.legislator.upsert(
                                        data=sub_legislator_query,
                                        conflict_column="bioguide_id"
                                    )
                                    logger.info(f"sub_legislator_insert: {sub_legislator_insert}")
                                    await self.uow.commit()
                                    if sub_legislator_insert: legislator_insert_cnt += 1
                                    membership_query = {"legislator_id": str(sub_legislator_insert.id), "committee_id": str(sub_committee_insert.id), "role": position}
                                    await self.uow.committee_membership.create(membership_query)
                                    await self.uow.commit()
                                        

            return { legislator_insert_cnt, committee_insert_cnt, sub_committee_insert_cnt }
        except Exception as e:
            logger.error(f"[Document download_reports] download_and_parse_xml reports: {e}")
            raise e
        