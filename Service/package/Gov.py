from typing import Optional, Literal
from .GovModel import CommitteeResponse


"""
https://api.congress.gov/#/
API related to the US Congress, including bills, amendments, and other legislative information.
"""


class CongressAPI:
    def __init__(self, api_key: str):
        self.api_key = os.getenv("CONGRESS_API_KEY")
        self.base_url = "https://api.congress.gov/v3"


    def get_committee_by_congress_chamber(self, congress: int, chamber: Literal["house", "senate", "joint"]) -> CommitteeResponse:
        """
        Retrieve committees for a given Congress session.
        
        Args:
            congress: Congress number (e.g., 119)
            chamber: 'house', 'senate', or 'joint'
            
        Returns:
            CommitteeResponse with committees list
        """
        valid_chambers = {"house", "senate", "joint"}
        if chamber not in valid_chambers:
            raise ValueError(f"Invalid chamber '{chamber}'. Must be one of: {valid_chambers}")
        
        url = f"{self.base_url}/committee/{congress}/{chamber}"
        params = {
            "format": "json",
            "offset": 0,
            "limit": 250,
            "api_key": self.api_key
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        return CommitteeResponse(**response.json())


    
    
