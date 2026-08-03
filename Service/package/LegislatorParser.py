"""
Legislator Parser for GitHub's unitedstates/congress-legislators repository
https://github.com/unitedstates/congress-legislators
"""

import httpx
import json
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class LegislatorId(BaseModel):
    """Model for legislator ID data"""
    bioguide: Optional[str] = None
    thomas: Optional[str] = None
    lis: Optional[str] = None
    govtrack: Optional[int] = None
    opensecrets: Optional[str] = None
    votesmart: Optional[int] = None
    fec: Optional[List[str]] = None
    cspan: Optional[int] = None
    wikipedia: Optional[str] = None
    house_history: Optional[int] = None
    ballotpedia: Optional[str] = None
    maplight: Optional[int] = None
    icpsr: Optional[int] = None
    wikidata: Optional[str] = None
    google_entity_id: Optional[str] = None
    pictorial: Optional[int] = None


class LegislatorName(BaseModel):
    """Model for legislator name data"""
    first: str
    last: str
    official_full: Optional[str] = None
    middle: Optional[str] = None
    suffix: Optional[str] = None
    nickname: Optional[str] = None


class LegislatorBio(BaseModel):
    """Model for legislator biographical data"""
    birthday: Optional[str] = None
    gender: Optional[str] = None


class LegislatorTerm(BaseModel):
    """Model for legislator term data"""
    type: str  # 'rep' or 'sen'
    start: str
    end: str
    state: str
    district: Optional[int] = None
    class_: Optional[int] = None  # For senators
    party: str
    url: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    contact_form: Optional[str] = None
    office: Optional[str] = None
    state_rank: Optional[str] = None
    rss_url: Optional[str] = None
    
    class Config:
        fields = {'class_': 'class'}


class LegislatorData(BaseModel):
    """Model for complete legislator data from GitHub JSON"""
    id: LegislatorId
    name: LegislatorName
    bio: LegislatorBio
    terms: List[LegislatorTerm]


class CongressLegislatorParser:
    """
    Parses legislator data from GitHub's unitedstates/congress-legislators repository.
    
    Fetches JSON from:
    https://unitedstates.github.io/congress-legislators/legislators-current.json
    https://unitedstates.github.io/congress-legislators/legislators-social-media.json
    
    Builds objects keyed to the oden.legislator table structure with:
    - Current term information (most recent term)
    - Active status based on current date vs term end date
    - Proper chamber identification (House vs Senate)
    - Social media handles (Twitter/X)
    """
    
    GITHUB_LEGISLATORS_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
    GITHUB_SOCIAL_MEDIA_URL = "https://unitedstates.github.io/congress-legislators/legislators-social-media.json"
    
    def __init__(self):
        """Initialize the parser."""
        self.raw_data: List[Dict[str, Any]] = []
        self.social_media_data: Dict[str, Dict[str, Any]] = {}  # Keyed by bioguide_id
        
    async def fetch_legislators(self) -> List[Dict[str, Any]]:
        """
        Fetch legislator data from GitHub.
        
        Returns:
            List of raw legislator dictionaries
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.GITHUB_LEGISLATORS_URL)
                response.raise_for_status()
                self.raw_data = response.json()
                logger.info(f"Fetched {len(self.raw_data)} legislators from GitHub")
                return self.raw_data
        except Exception as e:
            logger.error(f"Failed to fetch legislators from GitHub: {e}")
            raise
    
    async def fetch_social_media(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch social media data from GitHub.
        
        Returns:
            Dictionary keyed by bioguide_id with social media handles
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.GITHUB_SOCIAL_MEDIA_URL)
                response.raise_for_status()
                social_data = response.json()
                
                # Convert to dict keyed by bioguide_id for easy lookup
                self.social_media_data = {}
                for legislator in social_data:
                    bioguide_id = legislator.get("id", {}).get("bioguide")
                    if bioguide_id:
                        self.social_media_data[bioguide_id] = legislator.get("social", {})
                
                logger.info(f"Fetched social media data for {len(self.social_media_data)} legislators")
                return self.social_media_data
        except Exception as e:
            logger.warning(f"Failed to fetch social media data from GitHub: {e}")
            # Don't fail if social media data is unavailable
            return {}
    
    def _get_current_term(self, terms: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Get the most recent/current term from the terms list.
        
        Args:
            terms: List of term dictionaries
            
        Returns:
            Most recent term or None
        """
        if not terms:
            return None
        
        # Terms are typically in chronological order, get the last one
        return terms[-1]
    
    def _map_chamber(self, term_type: str) -> str:
        """
        Map term type to chamber name.
        
        Args:
            term_type: 'rep' or 'sen'
            
        Returns:
            'house' or 'senate'
        """
        chamber_map = {
            "rep": "house",
            "sen": "senate"
        }
        return chamber_map.get(term_type.lower(), term_type.lower())
    
    def _is_active(self, term_end: str) -> bool:
        """
        Determine if legislator is currently active based on term end date.
        
        Args:
            term_end: Term end date string (YYYY-MM-DD)
            
        Returns:
            True if term end date is in the future, False otherwise
        """
        try:
            end_date = datetime.strptime(term_end, "%Y-%m-%d")
            current_date = datetime.now()
            return end_date > current_date
        except Exception as e:
            logger.warning(f"Failed to parse term end date '{term_end}': {e}")
            # If we can't parse, assume active
            return True
    
    def _format_district(self, district: Optional[int]) -> Optional[str]:
        """
        Format district number as string.
        
        Args:
            district: District number (or None for senators)
            
        Returns:
            Formatted district string (e.g., '01', '15') or None
        """
        if district is None:
            return None
        
        # At-large districts are typically 0
        if district == 0:
            return "00"
        
        # Format with leading zero for single digits
        return f"{district:02d}"
    
    def _extract_leadership_role(self, term: Dict[str, Any], parsed_data: LegislatorData) -> Optional[str]:
        """
        Extract leadership role from term data.
        
        For now uses state_rank (senior/junior) but could be enhanced with:
        - Speaker of the House
        - Majority/Minority Leader
        - Whip positions
        - Committee chairs (from separate data)
        
        Args:
            term: Current term dictionary
            parsed_data: Parsed legislator data
            
        Returns:
            Leadership role string or None
        """
        # Use state_rank if available (e.g., "senior", "junior" for senators)
        state_rank = term.get("state_rank")
        if state_rank:
            return state_rank.title()  # Capitalize: "Senior", "Junior"
        
        return None
    
    def _get_twitter_handle(self, bioguide_id: str) -> Optional[str]:
        """
        Get Twitter/X handle from social media data.
        
        Args:
            bioguide_id: Legislator's bioguide ID
            
        Returns:
            Twitter handle (without @) or None
        """
        if not self.social_media_data:
            return None
        
        social = self.social_media_data.get(bioguide_id, {})
        
        # Try twitter first, then X (new name for Twitter)
        twitter = social.get("twitter") or social.get("x")
        
        if twitter:
            # Remove @ if present
            return twitter.lstrip("@")
        
        return None
    
    def build_legislator_object(self, legislator_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a legislator object for database insertion.
        
        Args:
            legislator_data: Raw legislator dictionary from JSON
            
        Returns:
            Dictionary keyed to oden.legislator table structure
        """
        try:
            # Parse with Pydantic model for validation
            parsed = LegislatorData(**legislator_data)
            
            # Get current term
            current_term = self._get_current_term(legislator_data.get("terms", []))
            
            if not current_term:
                logger.warning(f"No terms found for legislator {parsed.name.first} {parsed.name.last}")
                return None
            
            # Parse current term
            term = LegislatorTerm(**current_term)
            
            # Extract name components
            # Note: GitHub data doesn't have traditional "prefix" (Hon., Dr., etc.)
            # but might have suffix in name field
            prefix = None
            if hasattr(parsed.name, 'suffix') and parsed.name.suffix:
                # Suffix like "Jr.", "Sr.", "III" - not really a prefix but store somewhere
                prefix = parsed.name.suffix
            
            # Extract leadership role
            leadership_role = self._extract_leadership_role(current_term, parsed)
            
            # Get Twitter handle from social media data
            twitter_handle = self._get_twitter_handle(parsed.id.bioguide)
            
            # Serialize terms to JSON string for JSONB column
            terms_json = json.dumps(legislator_data.get("terms", [])) if legislator_data.get("terms") else None
            
            # Build the database object with all available fields
            db_object = {
                "bioguide_id": parsed.id.bioguide,
                "prefix": prefix,  # Will be None unless we add suffix here
                "first_name": parsed.name.first,
                "last_name": parsed.name.last,
                "official_full": parsed.name.official_full,
                "party": term.party,
                "state": term.state,
                "district": self._format_district(term.district),
                "chamber": self._map_chamber(term.type),
                "leadership_role": leadership_role,  # state_rank or None
                "gender": parsed.bio.gender,
                "thomas": parsed.id.thomas,
                "twitter_handle": twitter_handle,  # From social media data
                "terms": terms_json,  # JSON string for JSONB column
                "official_url": term.url,
                "is_active": self._is_active(term.end)
            }
            
            return db_object
            
        except Exception as e:
            logger.error(f"Failed to build legislator object: {e}")
            return None
    
    async def parse_all(self) -> List[Dict[str, Any]]:
        """
        Parse all legislators from GitHub JSON.
        
        Fetches both legislator data and social media data.
        
        Returns:
            List of legislator objects ready for database insertion
        """
        if not self.raw_data:
            await self.fetch_legislators()
        
        # Fetch social media data (Twitter handles, etc.)
        if not self.social_media_data:
            await self.fetch_social_media()
        
        results = []
        
        for legislator_data in self.raw_data:
            try:
                # Build legislator object
                legislator_object = self.build_legislator_object(legislator_data)
                
                if legislator_object:
                    results.append(legislator_object)
                    
            except Exception as e:
                name = legislator_data.get("name", {})
                full_name = f"{name.get('first', 'unknown')} {name.get('last', 'unknown')}"
                logger.error(f"Failed to parse legislator {full_name}: {e}")
                continue
        
        logger.info(f"Parsed {len(results)} legislators successfully")
        return results
    
    def get_legislator_details(self, legislator_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get detailed information about a legislator including all terms.
        
        Useful for analysis or detailed views, but not used for basic ingestion.
        
        Args:
            legislator_data: Raw legislator dictionary from JSON
            
        Returns:
            Dictionary with detailed legislator information
        """
        try:
            parsed = LegislatorData(**legislator_data)
            
            return {
                "bioguide_id": parsed.id.bioguide,
                "name": {
                    "first": parsed.name.first,
                    "last": parsed.name.last,
                    "official_full": parsed.name.official_full
                },
                "bio": {
                    "birthday": parsed.bio.birthday,
                    "gender": parsed.bio.gender
                },
                "terms_count": len(parsed.terms),
                "current_term": self._get_current_term(legislator_data.get("terms", [])),
                "all_terms": parsed.terms
            }
            
        except Exception as e:
            logger.error(f"Failed to get legislator details: {e}")
            return None
