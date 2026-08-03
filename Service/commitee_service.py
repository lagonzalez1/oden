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
    async def get_committees(self, filter: Dict)->List[Dict[str, any]]:
        try:
            async with self.uow:
                rows = await self.uow.committee.get_table(filters=filter)
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

    async def get_committees_by_bioguide_id(self, bioguide_id: str) -> List[Dict[str, Any]]:
        """Return all committees linked to a legislator via bioguide_id."""
        try:
            async with self.uow:
                rows = await self.uow.committee_membership.get_committees_by_bioguide_id(
                    bioguide_id=bioguide_id
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[get_committees_by_bioguide_id] error: {e}")
            raise

    async def compare_description_to_committee_chunks(
        self,
        description: str,
        bioguide_id: Optional[str] = None,
        limit: int = 10,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Embed `description` and rank committee_chunks by cosine similarity.

        If bioguide_id is provided, only compares against that member's committees.
        """
        if not description or not description.strip():
            return []

        try:
            embedding_service = EmbeddingService()
            embedding = await embedding_service.embed(description)

            async with self.uow:
                committee_ids = None
                if bioguide_id:
                    committees = await self.uow.committee_membership.get_committees_by_bioguide_id(
                        bioguide_id=bioguide_id
                    )
                    committee_ids = [str(c["id"]) for c in committees]
                    if not committee_ids:
                        logger.info(
                            f"[compare_description_to_committee_chunks] "
                            f"no committees for bioguide_id={bioguide_id}"
                        )
                        return []

                rows = await self.uow.committee_chunks.search_similar(
                    embedding=embedding,
                    committee_ids=committee_ids,
                    limit=limit,
                    min_score=min_score,
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[compare_description_to_committee_chunks] error: {e}")
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

    
    async def create_committee_embeddings(self) -> Dict[str, int]:
        """
        Create embeddings for all committees with jurisdiction text.
        
        Uses EmbeddingService to generate vector embeddings for committee jurisdictions
        and stores them in the committee_chunks table for similarity search.
        
        Returns:
            Dict with counts: {
                "total_committees": int,
                "embeddings_created": int,
                "skipped": int,
                "errors": int
            }
        """
        from Embeddings.main import EmbeddingService
        
        try:
            total_count = 0
            created_count = 0
            skipped_count = 0
            error_count = 0
            
            # Initialize embedding service
            embedding_service = EmbeddingService()
            
            async with self.uow:
                # Get all committees
                committees = await self.uow.committee.get_table(filters={})
                total_count = len(committees)
                
                logger.info(f"Processing {total_count} committees for embedding creation")
                
                for committee in committees:
                    try:
                        committee_id = committee.get("id")  # UUID
                        committee_code = committee.get("committee_id")  # e.g., 'SSAF'
                        jurisdiction_source = committee.get("jurisdiction_source")
                        title = committee.get("title", "Unknown")
                        
                        # Skip if no jurisdiction text
                        if not jurisdiction_source or jurisdiction_source.strip() == "":
                            logger.debug(f"Skipping {committee_code} - no jurisdiction text")
                            skipped_count += 1
                            continue
                        
                        # Generate embedding
                        logger.info(f"Creating embedding for {committee_code}: {title}")
                        embedding = await embedding_service.embed(jurisdiction_source)
                        
                        # Verify embedding dimensions
                        if len(embedding) != 1536:  # Adjust based on your model
                            logger.warning(f"Unexpected embedding dimensions: {len(embedding)} for {committee_code}")
                        
                        # Prepare embedding record
                        embedding_query = {
                            "committee_id": committee_id,
                            "content_type": "jurisdiction",
                            "chunk_index": 0, 
                            "chunk_text": jurisdiction_source,
                            "embedding": str(embedding)
                        }
                        
                        # Insert into database
                        await self.uow.committee_chunks.create(embedding_query)
                        await self.uow.commit()
                        
                        created_count += 1
                        logger.info(f"✅ Created embedding for {committee_code} ({created_count}/{total_count})")
                        
                    except Exception as e:
                        error_count += 1
                        logger.error(f"Failed to create embedding for {committee.get('committee_id', 'unknown')}: {e}")
                        await self.uow.rollback()
                        # Continue processing other committees
                        continue
                
            logger.info(
                f"Committee embedding creation complete: "
                f"{created_count} created, {skipped_count} skipped, {error_count} errors out of {total_count} total"
            )
            
            return {
                "total_committees": total_count,
                "embeddings_created": created_count,
                "skipped": skipped_count,
                "errors": error_count
            }
            
        except Exception as e:
            logger.error(f"[create_committee_embeddings] error: {e}")
            raise e
    
    async def ingest_committee_data_from_github(self) -> Dict[str, int]:
        """
        Ingest committee data from GitHub's congress-legislators repository.
        
        Uses CongressCommitteeParser to fetch and parse JSON from:
        https://unitedstates.github.io/congress-legislators/committees-current.json
        
        Implements top-down design:
        1. Insert parent committee
        2. Get parent committee UUID
        3. Insert subcommittees with parent_committee_id
        
        Returns:
            Dict with counts: {"committees": int, "subcommittees": int}
        """
        from Service.package.CommitteeParser import CongressCommitteeParser
        
        try:
            committee_count = 0
            subcommittee_count = 0
            
            # Initialize parser
            parser = CongressCommitteeParser(congress_num=119)
            
            # Fetch and parse all committees
            committees_with_subs = await parser.parse_all()
            
            async with self.uow:
                for parent_object, subcommittees_raw in committees_with_subs:
                    try:
                        # 1. Insert or update parent committee
                        parent_record = await self.uow.committee.upsert(
                            data=parent_object,
                            conflict_column="committee_id"
                        )
                        await self.uow.commit()
                        
                        if parent_record:
                            committee_count += 1
                            parent_uuid = str(parent_record.get("id"))
                            parent_thomas_id = parent_object["committee_id"]
                            chamber = parent_object["chamber"]
                            
                            # 2. Build subcommittee objects with parent_committee_id
                            if subcommittees_raw:
                                subcommittee_objects = parser.build_subcommittee_objects(
                                    parent_committee_id=parent_uuid,
                                    parent_thomas_id=parent_thomas_id,
                                    subcommittees=subcommittees_raw,
                                    chamber=chamber
                                )
                                
                                # 3. Insert each subcommittee
                                for sub_object in subcommittee_objects:
                                    sub_record = await self.uow.committee.upsert(
                                        data=sub_object,
                                        conflict_column="committee_id"
                                    )
                                    await self.uow.commit()
                                    
                                    if sub_record:
                                        subcommittee_count += 1
                                        
                    except Exception as e:
                        logger.error(f"Failed to insert committee {parent_object.get('title', 'unknown')}: {e}")
                        await self.uow.rollback()
                        continue
            
            logger.info(f"Ingested {committee_count} committees and {subcommittee_count} subcommittees from GitHub")
            return {
                "committees": committee_count,
                "subcommittees": subcommittee_count
            }
            
        except Exception as e:
            logger.error(f"[ingest_committee_data_from_github] Failed: {e}")
            raise

    async def ingest_legislators_from_github(self) -> Dict[str, int]:
        """
        Ingest legislator data from GitHub's congress-legislators repository.
        
        Uses CongressLegislatorParser to fetch and parse JSON from:
        https://unitedstates.github.io/congress-legislators/legislators-current.json
        https://unitedstates.github.io/congress-legislators/legislators-social-media.json
        
        Inserts or updates legislators based on their current term.
        Includes social media handles (Twitter/X) when available.
        Does NOT create committee_membership relationships (handled separately).
        
        Returns:
            Dict with counts: {"legislators": int, "active": int, "inactive": int, "with_twitter": int}
        """
        from Service.package.LegislatorParser import CongressLegislatorParser
        
        try:
            legislator_count = 0
            active_count = 0
            inactive_count = 0
            twitter_count = 0
            
            # Initialize parser
            parser = CongressLegislatorParser()
            
            # Fetch and parse all legislators (includes social media data)
            legislators = await parser.parse_all()
            
            async with self.uow:
                for legislator_object in legislators:
                    try:
                        # Insert or update legislator
                        legislator_record = await self.uow.legislator.upsert(
                            data=legislator_object,
                            conflict_column="bioguide_id"
                        )
                        await self.uow.commit()
                        
                        if legislator_record:
                            legislator_count += 1
                            
                            # Track active vs inactive
                            if legislator_object.get("is_active", True):
                                active_count += 1
                            else:
                                inactive_count += 1
                            
                            # Track Twitter handles
                            if legislator_object.get("twitter_handle"):
                                twitter_count += 1
                                
                    except Exception as e:
                        bioguide = legislator_object.get('bioguide_id', 'unknown')
                        name = f"{legislator_object.get('first_name', '')} {legislator_object.get('last_name', '')}"
                        logger.error(f"Failed to insert legislator {name} ({bioguide}): {e}")
                        await self.uow.rollback()
                        continue
            
            logger.info(f"Ingested {legislator_count} legislators from GitHub ({active_count} active, {inactive_count} inactive, {twitter_count} with Twitter)")
            return {
                "legislators": legislator_count,
                "active": active_count,
                "inactive": inactive_count,
                "with_twitter": twitter_count
            }
            
        except Exception as e:
            logger.error(f"[ingest_legislators_from_github] Failed: {e}")
            raise

    async def ingest_committee_memberships_from_github(self) -> Dict[str, int]:
        """
        Ingest committee membership data from GitHub's congress-legislators repository.
        
        Uses CongressCommitteeMembershipParser to fetch and parse JSON from:
        https://unitedstates.github.io/congress-legislators/committee-membership-current.json
        
        Links legislators to committees based on:
        - bioguide_id -> legislator UUID lookup
        - committee_thomas_id -> committee UUID lookup
        
        Prerequisites:
        - Legislators must be ingested first (bioguide_id references)
        - Committees must be ingested first (committee_id references)
        
        Returns:
            Dict with counts: {"memberships": int, "skipped": int, "committees": int}
        """
        from Service.package.CommitteeParser import CongressCommitteeMembershipParser
        
        try:
            membership_count = 0
            skipped_count = 0
            committees_processed = set()
            
            # Initialize parser
            parser = CongressCommitteeMembershipParser()
            
            # Fetch and parse all memberships
            memberships = await parser.parse_all()
            
            async with self.uow:
                for membership_object in memberships:
                    try:
                        bioguide_id = membership_object.get("bioguide_id")
                        committee_thomas_id = membership_object.get("committee_thomas_id")
                        
                        # Lookup legislator UUID by bioguide_id
                        legislator = await self.uow.legislator.get_table(
                            filters={"bioguide_id": bioguide_id}
                        )
                        
                        if not legislator or len(legislator) == 0:
                            logger.warning(f"Legislator not found for bioguide_id: {bioguide_id}")
                            skipped_count += 1
                            continue
                        
                        legislator_id = str(legislator[0].get("id"))
                        
                        # Lookup committee UUID by committee_id (thomas_id)
                        committee = await self.uow.committee.get_table(
                            filters={"committee_id": committee_thomas_id}
                        )
                        
                        if not committee or len(committee) == 0:
                            logger.warning(f"Committee not found for thomas_id: {committee_thomas_id}")
                            skipped_count += 1
                            continue
                        
                        committee_id = str(committee[0].get("id"))
                        committees_processed.add(committee_thomas_id)
                        
                        # Build final membership record with UUIDs
                        membership_data = {
                            "legislator_id": legislator_id,
                            "committee_id": committee_id,
                            "role": membership_object.get("role"),
                            "rank_in_party": membership_object.get("rank_in_party"),
                            "is_ex_officio": membership_object.get("is_ex_officio", False),
                            "assignment_date": membership_object.get("assignment_date")
                        }
                        
                        # Upsert membership (handle duplicates gracefully)
                        await self.uow.committee_membership.upsert(
                            data=membership_data,
                            conflict_column="legislator_id,committee_id"  # Composite unique constraint
                        )
                        await self.uow.commit()
                        
                        membership_count += 1
                        
                    except Exception as e:
                        bioguide = membership_object.get('bioguide_id', 'unknown')
                        committee = membership_object.get('committee_thomas_id', 'unknown')
                        logger.error(f"Failed to insert membership for {bioguide} -> {committee}: {e}")
                        await self.uow.rollback()
                        skipped_count += 1
                        continue
            
            logger.info(f"Ingested {membership_count} committee memberships from GitHub (skipped {skipped_count}, {len(committees_processed)} committees)")
            return {
                "memberships": membership_count,
                "skipped": skipped_count,
                "committees": len(committees_processed)
            }
            
        except Exception as e:
            logger.error(f"[ingest_committee_memberships_from_github] Failed: {e}")
            raise

