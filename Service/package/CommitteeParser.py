

"""
https://github.com/unitedstates/congress-legislators
"""

import httpx
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class SubcommitteeData(BaseModel):
    """Model for subcommittee data from GitHub JSON"""
    name: str
    thomas_id: str
    address: Optional[str] = None
    phone: Optional[str] = None


class CommitteeData(BaseModel):
    """Model for committee data from GitHub JSON"""
    type: str  # house, senate, joint
    name: str
    url: Optional[str] = None
    minority_url: Optional[str] = None
    thomas_id: str
    house_committee_id: Optional[str] = None
    senate_committee_id: Optional[str] = None
    subcommittees: List[SubcommitteeData] = []
    address: Optional[str] = None
    phone: Optional[str] = None
    rss_url: Optional[str] = None
    jurisdiction: Optional[str] = None
    jurisdiction_source: Optional[str] = None
    youtube_id: Optional[str] = None


class CongressCommitteeParser:
    """
    Parses committee data from GitHub's unitedstates/congress-legislators repository.
    
    Fetches JSON from:
    https://unitedstates.github.io/congress-legislators/committees-current.json
    
    Builds objects keyed to the oden.committee table structure with:
    - Parent committees first (top-down design)
    - Subcommittees linked via parent_committee_id
    - Committee IDs using thomas_id from JSON
    - Subcommittee IDs as parent_thomas_id + subcommittee_thomas_id
    """
    
    GITHUB_COMMITTEES_URL = "https://unitedstates.github.io/congress-legislators/committees-current.json"
    
    def __init__(self, congress_num: Optional[int] = 119):
        """
        Initialize the parser.
        
        Args:
            congress_num: Congress number (default: 119)
        """
        self.congress_num = congress_num
        self.raw_data: List[Dict[str, Any]] = []
        
    async def fetch_committees(self) -> List[Dict[str, Any]]:
        """
        Fetch committee data from GitHub.
        
        Returns:
            List of raw committee dictionaries
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.GITHUB_COMMITTEES_URL)
                response.raise_for_status()
                self.raw_data = response.json()
                logger.info(f"Fetched {len(self.raw_data)} committees from GitHub")
                return self.raw_data
        except Exception as e:
            logger.error(f"Failed to fetch committees from GitHub: {e}")
            raise
    
    def _map_chamber(self, committee_type: str) -> str:
        """
        Map committee type to chamber name.
        
        Args:
            committee_type: 'house', 'senate', or 'joint'
            
        Returns:
            Normalized chamber name
        """
        type_map = {
            "house": "house",
            "senate": "senate",
            "joint": "joint"
        }
        return type_map.get(committee_type.lower(), committee_type.lower())
    
    def _generate_subcommittee_id(self, parent_thomas_id: str, sub_thomas_id: str) -> str:
        """
        Generate committee_id for subcommittees.
        
        Args:
            parent_thomas_id: Parent committee thomas_id (e.g., 'HSAG')
            sub_thomas_id: Subcommittee thomas_id (e.g., '15')
            
        Returns:
            Combined ID (e.g., 'HSAG15')
        """
        return f"{parent_thomas_id}{sub_thomas_id}"
    
    def build_committee_object(self, committee_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a committee object for database insertion (parent committee only).
        
        Args:
            committee_data: Raw committee dictionary from JSON
            
        Returns:
            Dictionary keyed to oden.committee table structure
        """
        try:
            # Parse with Pydantic model for validation
            parsed = CommitteeData(**committee_data)
            
            # Build the database object
            db_object = {
                "committee_id": parsed.thomas_id,
                "parent_committee_id": None,
                "congress_num": self.congress_num,
                "chamber": self._map_chamber(parsed.type),
                "committee_type": "standing",  # Default, can be enhanced
                "senate_committee_id": parsed.senate_committee_id,
                "house_committee_id": parsed.house_committee_id,
                "title": parsed.name,
                "jurisdiction_source": parsed.jurisdiction or parsed.jurisdiction_source,
                "youtube_id": parsed.youtube_id,
                "url": parsed.url,
                "office": parsed.address,
                "is_subcommittee": False,
                "tags": []
            }
            
            return db_object
            
        except Exception as e:
            logger.error(f"Failed to build committee object: {e}")
            raise
    
    def build_subcommittee_objects(
        self, 
        parent_committee_id: str,  # UUID from DB after parent insert
        parent_thomas_id: str,
        subcommittees: List[Dict[str, Any]],
        chamber: str
    ) -> List[Dict[str, Any]]:
        """
        Build subcommittee objects for database insertion.
        
        Args:
            parent_committee_id: UUID of parent committee (from DB)
            parent_thomas_id: Thomas ID of parent committee
            subcommittees: List of subcommittee dictionaries
            chamber: Chamber name (house, senate, joint)
            
        Returns:
            List of dictionaries keyed to oden.committee table structure
        """
        subcommittee_objects = []
        
        for sub_data in subcommittees:
            try:
                # Parse with Pydantic model
                parsed = SubcommitteeData(**sub_data)
                
                # Generate subcommittee ID
                sub_committee_id = self._generate_subcommittee_id(
                    parent_thomas_id, 
                    parsed.thomas_id
                )
                
                # Build the database object
                db_object = {
                    "committee_id": sub_committee_id,
                    "parent_committee_id": parent_committee_id,  # Link to parent
                    "congress_num": self.congress_num,
                    "chamber": chamber,
                    "committee_type": "standing",
                    "senate_committee_id": None,
                    "house_committee_id": None,
                    "title": parsed.name,
                    "jurisdiction_source": None,
                    "youtube_id": None,
                    "url": None,
                    "office": parsed.address,
                    "is_subcommittee": True,  # Mark as subcommittee
                    "tags": []
                }
                
                subcommittee_objects.append(db_object)
                
            except Exception as e:
                logger.error(f"Failed to build subcommittee object: {e}")
                continue
        
        return subcommittee_objects
    
    async def parse_all(self) -> List[tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Parse all committees from GitHub JSON.
        
        Returns top-down structure:
        List of tuples: (parent_committee_object, [subcommittee_objects])
        
        This allows the service to:
        1. Insert parent committee
        2. Get parent committee UUID
        3. Insert subcommittees with parent_committee_id set
        
        Returns:
            List of (parent_dict, subcommittees_list) tuples
        """
        if not self.raw_data:
            await self.fetch_committees()
        
        results = []
        
        for committee_data in self.raw_data:
            try:
                # Build parent committee object
                parent_object = self.build_committee_object(committee_data)
                
                # Store subcommittees data for later (needs parent_committee_id from DB)
                subcommittees_raw = committee_data.get("subcommittees", [])
                
                # Package as tuple: (parent, subcommittees_raw)
                results.append((parent_object, subcommittees_raw))
                
            except Exception as e:
                logger.error(f"Failed to parse committee {committee_data.get('name', 'unknown')}: {e}")
                continue
        
        logger.info(f"Parsed {len(results)} committees with subcommittees")
        return results

    


class CommitteeMemberData(BaseModel):
    """Model for committee member data from membership JSON"""
    name: str
    party: str  # "majority" or "minority"
    rank: int
    title: Optional[str] = None  # "Chairman", "Ranking Member", "Vice Chairman", etc.
    bioguide: str


class CongressCommitteeMembershipParser:
    """
    Parses committee membership data from GitHub's unitedstates/congress-legislators repository.
    
    Fetches JSON from:
    https://unitedstates.github.io/congress-legislators/committee-membership-current.json
    
    Builds objects keyed to the oden.committee_membership table structure.
    
    JSON Structure:
    {
      "SSAF": [member1, member2, ...],  # Committee ID -> list of members
      "HSAG": [member1, member2, ...],
      ...
    }
    """
    
    GITHUB_MEMBERSHIP_URL = "https://unitedstates.github.io/congress-legislators/committee-membership-current.json"
    
    def __init__(self):
        """Initialize the parser."""
        self.raw_data: Dict[str, List[Dict[str, Any]]] = {}
        
    async def fetch_memberships(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch committee membership data from GitHub.
        
        Returns:
            Dictionary keyed by committee_id with list of members
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.GITHUB_MEMBERSHIP_URL)
                response.raise_for_status()
                self.raw_data = response.json()
                
                total_members = sum(len(members) for members in self.raw_data.values())
                logger.info(f"Fetched memberships for {len(self.raw_data)} committees ({total_members} total members)")
                return self.raw_data
        except Exception as e:
            logger.error(f"Failed to fetch committee memberships from GitHub: {e}")
            raise
    
    def build_membership_object(
        self,
        committee_id: str,
        member_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build a committee membership object for database insertion.
        
        Args:
            committee_id: Committee thomas_id (key from JSON)
            member_data: Raw member dictionary from JSON
            
        Returns:
            Dictionary with bioguide_id and membership details (needs legislator_id and committee UUID from DB)
        """
        try:
            # Parse with Pydantic model for validation
            parsed = CommitteeMemberData(**member_data)
            
            # Determine role from title
            role = parsed.title if parsed.title else "Member"
            
            # Build the membership object
            # Note: legislator_id and committee_id (UUID) will be resolved by service layer
            membership_object = {
                "bioguide_id": parsed.bioguide,  # Used to lookup legislator_id
                "committee_thomas_id": committee_id,  # Used to lookup committee_id (UUID)
                "role": role,
                "rank_in_party": parsed.rank,
                "party": parsed.party,  # "majority" or "minority"
                "is_ex_officio": False,  # Not in GitHub data
                "assignment_date": None  # Not in GitHub data
            }
            
            return membership_object
            
        except Exception as e:
            logger.error(f"Failed to build membership object for {member_data.get('name', 'unknown')}: {e}")
            return None
    
    async def parse_all(self) -> List[Dict[str, Any]]:
        """
        Parse all committee memberships from GitHub JSON.
        
        Returns:
            List of membership objects with bioguide_id and committee_thomas_id
            (Service layer will resolve to UUIDs)
        """
        if not self.raw_data:
            await self.fetch_memberships()
        
        results = []
        
        for committee_thomas_id, members in self.raw_data.items():
            for member_data in members:
                try:
                    membership_object = self.build_membership_object(
                        committee_thomas_id,
                        member_data
                    )
                    
                    if membership_object:
                        results.append(membership_object)
                        
                except Exception as e:
                    logger.error(f"Failed to parse membership for committee {committee_thomas_id}: {e}")
                    continue
        
        logger.info(f"Parsed {len(results)} committee memberships")
        return results
    
    def get_committee_members(self, committee_thomas_id: str) -> List[Dict[str, Any]]:
        """
        Get all members for a specific committee.
        
        Args:
            committee_thomas_id: Committee thomas_id (e.g., 'SSAF', 'HSAG')
            
        Returns:
            List of membership objects for that committee
        """
        if not self.raw_data:
            logger.warning("No data loaded. Call fetch_memberships() first.")
            return []
        
        members = self.raw_data.get(committee_thomas_id, [])
        
        return [
            self.build_membership_object(committee_thomas_id, member)
            for member in members
            if self.build_membership_object(committee_thomas_id, member)
        ]
